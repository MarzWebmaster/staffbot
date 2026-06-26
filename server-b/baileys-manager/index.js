#!/usr/bin/env node
/**
 * StaffBot.my — Baileys Multi-Session Manager
 * 
 * Manages multiple WhatsApp sessions — one per client.
 * Each client has their own auth folder, WhatsApp number, and session.
 * 
 * API Endpoints:
 *   POST /api/session/init   — Init a new WhatsApp session (returns QR)
 *   GET  /api/session/:id/qr  — Get current QR code for a session
 *   GET  /api/session/:id/status — Get session connection status
 *   POST /api/session/:id/send — Send a message via a client's session
 *   GET  /api/sessions        — List all active/inactive sessions
 *   POST /api/session/:id/logout — Logout a client's WhatsApp session
 * 
 * Incoming messages are relayed to the Gateway → routed to correct container.
 */

const express = require('express');
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const QRCode = require('qrcode');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// --- Config ---
const HTTP_PORT = parseInt(process.env.HTTP_PORT || '8653');
const GATEWAY_URL = process.env.GATEWAY_URL || 'http://staffbot-gateway:8080';
const GATEWAY_AUTH_KEY = process.env.GATEWAY_AUTH_KEY || 'staffbot-secret-key';
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const AUTH_BASE = process.env.AUTH_BASE || '/root/staffbot/auth/whatsapp';

const logger = pino({ level: LOG_LEVEL, name: 'baileys-manager' });

// --- State ---
const sessions = {};  // { clientId: { sock, authPath, number, status, qr, qrTimeout } }
const app = express();
app.use(express.json());

// --- Helper: Create auth dir for a client ---
function getAuthPath(clientId) {
    return path.join(AUTH_BASE, `client_${clientId}`);
}

// --- Helper: Notify Gateway about incoming message ---
async function notifyGateway(clientId, msgData) {
    try {
        await axios.post(`${GATEWAY_URL}/api/incoming/whatsapp/${clientId}`, msgData, {
            headers: { 'X-API-Key': GATEWAY_AUTH_KEY, 'x-gateway-key': GATEWAY_AUTH_KEY },
            timeout: 5000,
        });
    } catch (err) {
        logger.error({ clientId, error: err.message }, 'Failed to notify gateway of incoming message');
    }
}

// --- Init a WhatsApp session for a client ---
async function initSession(clientId, authPath) {
    if (sessions[clientId] && sessions[clientId].sock) {
        logger.info({ clientId }, 'Session already exists, closing old one first');
        await cleanupSession(clientId);
    }

    // Ensure auth directory exists
    const authDir = authPath || getAuthPath(clientId);
    fs.mkdirSync(authDir, { recursive: true });

    const sessionState = {
        clientId,
        authPath: authDir,
        sock: null,
        number: null,
        status: 'initializing',
        qr: null,
        qrTimeout: null,
        connectedAt: null,
    };
    sessions[clientId] = sessionState;

    try {
        const { state, saveCreds } = await useMultiFileAuthState(authDir);
        const { version } = await fetchLatestBaileysVersion();

        const sock = makeWASocket({
            version,
            auth: state,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            syncFullHistory: false,
            markOnlineOnConnect: false,
        });

        sessionState.sock = sock;

        // --- Connection update handler ---
        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                // Generate QR as data URL for the client to scan in dashboard
                try {
                    sessionState.qr = await QRCode.toDataURL(qr);
                    logger.info({ clientId }, 'New QR code generated');
                } catch (err) {
                    logger.error({ clientId, error: err.message }, 'Failed to generate QR image');
                }
            }

            if (connection === 'open') {
                sessionState.status = 'connected';
                sessionState.number = sock.user?.id?.split(':')[0] || 'unknown';
                sessionState.connectedAt = new Date().toISOString();
                sessionState.qr = null;
                logger.info({ clientId, number: sessionState.number }, '✅ WhatsApp connected');

                // Notify Gateway that this client's WhatsApp is connected
                await notifyGateway(clientId, {
                    type: 'connection_update',
                    status: 'connected',
                    number: sessionState.number,
                });
            }

            if (connection === 'close') {
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const reason = statusCode || lastDisconnect?.error?.message || 'unknown';
                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

                sessionState.status = 'disconnected';
                logger.warn({ clientId, reason, shouldReconnect }, '🔴 WhatsApp disconnected');

                if (shouldReconnect) {
                    sessionState.status = 'reconnecting';
                    logger.info({ clientId }, '🔄 Reconnecting in 5s...');
                    setTimeout(() => initSession(clientId, authPath), 5000);
                } else {
                    sessionState.status = 'logged_out';
                    logger.info({ clientId }, '🔴 Logged out. QR scan required.');
                    // Notify gateway
                    await notifyGateway(clientId, {
                        type: 'connection_update',
                        status: 'logged_out',
                    });
                }
            }
        });

        // --- Creds update handler ---
        sock.ev.on('creds.update', saveCreds);

        // --- Messages handler ---
        sock.ev.on('messages.upsert', async ({ messages }) => {
            for (const msg of messages) {
                // Skip own messages
                if (msg.key.fromMe) continue;

                const jid = msg.key.remoteJid;
                const isGroup = jid.endsWith('@g.us');
                const text = msg.message?.conversation 
                    || msg.message?.extendedTextMessage?.text 
                    || msg.message?.imageMessage?.caption
                    || '';

                if (!text) continue;

                const sender = msg.key.participant || jid;
                const pushName = msg.pushName || '';

                logger.info({ clientId, from: sender, text: text.substring(0, 80) }, '📨 Incoming WhatsApp message');

                // Relay to Gateway → routes to client's container
                await notifyGateway(clientId, {
                    type: 'message',
                    platform: 'whatsapp',
                    from: sender,
                    jid: jid,
                    text: text,
                    pushName: pushName,
                    isGroup: isGroup,
                    timestamp: msg.messageTimestamp,
                    messageId: msg.key.id,
                });
            }
        });

        return sessions[clientId];
    } catch (err) {
        logger.error({ clientId, error: err.message }, 'Failed to init session');
        sessionState.status = 'error';
        sessionState.error = err.message;
        return sessionState;
    }
}

// --- Cleanup a session ---
async function cleanupSession(clientId) {
    const session = sessions[clientId];
    if (!session) return;

    if (session.qrTimeout) clearTimeout(session.qrTimeout);
    if (session.sock) {
        try {
            session.sock.end(new Error('Session cleanup'));
            session.sock.ws?.close();
        } catch (err) {
            // ignore
        }
    }
    delete sessions[clientId];
}

// --- Send a message via a client's WhatsApp session ---
async function sendMessage(clientId, to, text) {
    const session = sessions[clientId];
    if (!session || !session.sock) {
        throw new Error(`No active session for client ${clientId}`);
    }
    if (session.status !== 'connected') {
        throw new Error(`WhatsApp not connected for client ${clientId} (status: ${session.status})`);
    }

    const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;
    await session.sock.sendMessage(jid, { text });
    logger.info({ clientId, to: jid }, '📤 WhatsApp message sent');
    return { success: true };
}

// =====================
// HTTP API ROUTES
// =====================

// --- Init a new WhatsApp session ---
app.post('/api/session/init', async (req, res) => {
    try {
        const { client_id, auth_path } = req.body;
        if (!client_id) {
            return res.status(400).json({ success: false, error: 'client_id required' });
        }
        
        const session = await initSession(client_id, auth_path);
        
        // Wait a moment for QR to generate
        await new Promise(r => setTimeout(r, 1000));

        res.json({
            success: true,
            client_id,
            status: session.status,
            qr_url: session.qr || null,
            message: session.qr ? 'QR code generated. Scan to connect.' : 'Session initializing. Check /qr endpoint.',
        });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// --- Get QR code for a session ---
app.get('/api/session/:clientId/qr', (req, res) => {
    const session = sessions[req.params.clientId];
    if (!session) {
        return res.status(404).json({ success: false, error: 'Session not found' });
    }
    if (!session.qr) {
        return res.json({ success: true, qr_available: false, status: session.status });
    }
    res.json({ success: true, qr_url: session.qr, status: session.status });
});

// --- Get session connection status ---
app.get('/api/session/:clientId/status', (req, res) => {
    const session = sessions[req.params.clientId];
    if (!session) {
        return res.json({ success: true, client_id: parseInt(req.params.clientId), status: 'not_found' });
    }
    res.json({
        success: true,
        client_id: session.clientId,
        status: session.status,
        number: session.number,
        connected_at: session.connectedAt,
    });
});

// --- Send a message ---
app.post('/api/session/:clientId/send', async (req, res) => {
    try {
        const { to, text } = req.body;
        if (!to || !text) {
            return res.status(400).json({ success: false, error: 'to and text required' });
        }
        const result = await sendMessage(parseInt(req.params.clientId), to, text);
        res.json(result);
    } catch (err) {
        res.status(400).json({ success: false, error: err.message });
    }
});

// --- List all sessions ---
app.get('/api/sessions', (req, res) => {
    const list = Object.values(sessions).map(s => ({
        client_id: s.clientId,
        status: s.status,
        number: s.number,
        connected_at: s.connectedAt,
        has_qr: !!s.qr,
    }));
    res.json({ success: true, count: list.length, sessions: list });
});

// --- Logout a session ---
app.post('/api/session/:clientId/logout', async (req, res) => {
    try {
        const session = sessions[req.params.clientId];
        if (!session) {
            return res.status(404).json({ success: false, error: 'Session not found' });
        }
        
        // Delete auth folder
        const authDir = session.authPath;
        if (authDir && fs.existsSync(authDir)) {
            fs.rmSync(authDir, { recursive: true, force: true });
        }
        
        await cleanupSession(parseInt(req.params.clientId));
        res.json({ success: true, message: 'WhatsApp session logged out and auth deleted' });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// --- Health check ---
app.get('/health', (req, res) => {
    const activeCount = Object.values(sessions).filter(s => s.status === 'connected').length;
    res.json({
        status: 'ok',
        service: 'StaffBot.my Baileys Multi-Session Manager',
        sessions: Object.keys(sessions).length,
        active_connections: activeCount,
    });
});

// =====================
// START
// =====================
app.listen(HTTP_PORT, () => {
    logger.info(`🚀 Baileys Multi-Session Manager running on port ${HTTP_PORT}`);
    logger.info(`📡 Gateway URL: ${GATEWAY_URL}`);
    logger.info(`🔑 Auth base: ${AUTH_BASE}`);
});
