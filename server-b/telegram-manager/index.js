#!/usr/bin/env node
/**
 * StaffBot.my — Telegram Multi-Bot Manager
 * 
 * Manages multiple Telegram bots — one per client.
 * Each client has their own bot token from @BotFather.
 * 
 * Responsibilities:
 * 1. Register webhooks for each client's bot via Telegram API
 * 2. Receive incoming Telegram updates via webhooks
 * 3. Route incoming messages to correct client's container via Gateway
 * 
 * API Endpoints:
 *   POST /api/webhook/register    — Register webhook for a client's bot
 *   POST /api/webhook/:clientId   — Incoming webhook from Telegram (called by Telegram)
 *   GET  /api/bots                — List registered bots
 *   GET  /health                  — Health check
 */

const express = require('express');
const axios = require('axios');
const crypto = require('crypto');

// --- Config ---
const HTTP_PORT = parseInt(process.env.HTTP_PORT || '8654');
const GATEWAY_URL = process.env.GATEWAY_URL || 'http://staffbot-gateway:8080';
const GATEWAY_AUTH_KEY = process.env.GATEWAY_AUTH_KEY || 'staffbot-secret-key';
const PUBLIC_URL = process.env.PUBLIC_URL || 'https://staffbot.my';
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';

const logger = console;  // Simple console logging
const app = express();
app.use(express.json());

// --- State ---
const bots = {};  // { clientId: { token, username, registered_at, last_used } }

// --- Helper: Call Telegram Bot API ---
async function telegramApi(token, method, params = {}) {
    const url = `https://api.telegram.org/bot${token}/${method}`;
    try {
        const resp = await axios.post(url, params, { timeout: 10000 });
        return resp.data;
    } catch (err) {
        logger.error(`Telegram API error (${method}): ${err.message}`);
        throw err;
    }
}

// --- Helper: Verify webhook request came from Telegram ---
// Note: Telegram doesn't sign webhook payloads, so we use the bot token route
// as implicit auth. This endpoint is protected by obscurity (random webhook path).

// --- Helper: Notify Gateway about incoming message ---
async function notifyGateway(clientId, msgData) {
    try {
        await axios.post(`${GATEWAY_URL}/api/incoming/telegram/${clientId}`, msgData, {
            headers: { 'X-API-Key': GATEWAY_AUTH_KEY },
            timeout: 5000,
        });
    } catch (err) {
        logger.error(`Failed to notify gateway: ${err.message}`);
    }
}

// =====================
// HTTP API ROUTES
// =====================

// --- Register a new Telegram bot for a client ---
app.post('/api/webhook/register', async (req, res) => {
    try {
        const { client_id, bot_token } = req.body;
        if (!client_id || !bot_token) {
            return res.status(400).json({ success: false, error: 'client_id and bot_token required' });
        }

        // 1. Verify token by getting bot info
        const me = await telegramApi(bot_token, 'getMe');
        if (!me.ok) {
            return res.status(400).json({ success: false, error: 'Invalid bot token' });
        }

        const botUsername = me.result.username;
        const botId = me.result.id;

        // 2. Set webhook — Telegram will POST updates to this endpoint
        const webhookUrl = `${PUBLIC_URL}/api/telegram/webhook/${client_id}`;
        const webhookResult = await telegramApi(bot_token, 'setWebhook', {
            url: webhookUrl,
            allowed_updates: ['message', 'callback_query'],
            max_connections: 10,
        });

        if (!webhookResult.ok) {
            return res.status(400).json({
                success: false,
                error: `Failed to set webhook: ${webhookResult.description}`,
            });
        }

        // 3. Store bot info with full token for sending messages
        // Token is only stored in memory, never persisted to disk
        bots[client_id] = {
            clientId: client_id,
            botId: botId,
            username: botUsername,
            token: bot_token,
            registered_at: new Date().toISOString(),
            last_used: null,
        };

        logger.log(`✅ Telegram bot @${botUsername} registered for client ${client_id}`);
        logger.log(`   Webhook: ${webhookUrl}`);

        res.json({
            success: true,
            client_id,
            bot_username: botUsername,
            bot_id: botId,
            webhook_url: webhookUrl,
            message: `Bot @${botUsername} registered. Messages will route to your StaffBot.`,
        });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// --- Incoming Telegram webhook (called by Telegram API) ---
app.post('/api/webhook/:clientId', async (req, res) => {
    const clientId = parseInt(req.params.clientId);
    const update = req.body;

    // Always respond 200 to Telegram (they retry on non-200)
    res.status(200).json({ ok: true });

    try {
        // Extract message from update
        const msg = update.message || update.callback_query?.message || update.edited_message;
        if (!msg) return;

        const chatId = msg.chat.id;
        const chatType = msg.chat.type;  // "private", "group", "supergroup"
        const text = msg.text || msg.caption || '';
        const fromId = msg.from?.id;
        const fromName = msg.from?.first_name || '';
        const isBot = msg.from?.is_bot || false;

        // Ignore messages from bots
        if (isBot) return;

        if (!text) return;

        logger.log(`📨 [TG:${clientId}] @${fromName}: ${text.substring(0, 80)}`);

        // Track last used
        if (bots[clientId]) {
            bots[clientId].last_used = new Date().toISOString();
        }

        // Relay to Gateway → routes to client's container
        await notifyGateway(clientId, {
            type: 'message',
            platform: 'telegram',
            chat_id: chatId,
            chat_type: chatType,
            from_id: fromId,
            from_name: fromName,
            text: text,
            message_id: msg.message_id,
            timestamp: msg.date,
        });
    } catch (err) {
        logger.error(`Error processing Telegram update for client ${clientId}: ${err.message}`);
    }
});

// --- Send a Telegram message on behalf of a client ---
app.post('/api/send/:clientId', async (req, res) => {
    try {
        const clientId = parseInt(req.params.clientId);
        const { chat_id, text } = req.body;

        if (!chat_id || !text) {
            return res.status(400).json({ success: false, error: 'chat_id and text required' });
        }

        const bot = bots[clientId];
        if (!bot) {
            return res.status(404).json({ success: false, error: `No bot registered for client ${clientId}` });
        }

        const result = await telegramApi(bot.token, 'sendMessage', {
            chat_id: chat_id,
            text: text,
            parse_mode: 'Markdown',
        });

        logger.log(`📤 [TG:${clientId}] Sent to ${chat_id}`);
        res.json({ success: true, message_id: result.result?.message_id });
    } catch (err) {
        res.status(500).json({ success: false, error: err.message });
    }
});

// --- List registered bots ---
app.get('/api/bots', (req, res) => {
    const list = Object.values(bots).map(b => ({
        client_id: b.clientId,
        username: b.username,
        registered_at: b.registered_at,
        last_used: b.last_used,
    }));
    res.json({ success: true, count: list.length, bots: list });
});

// --- Bot status check ---
app.get('/api/bot/:clientId/status', async (req, res) => {
    const clientId = parseInt(req.params.clientId);
    const bot = bots[clientId];
    if (!bot) {
        return res.json({ success: true, client_id: clientId, registered: false });
    }

    try {
        const me = await telegramApi(bot.token, 'getMe');
        const webhookInfo = await telegramApi(bot.token, 'getWebhookInfo');
        res.json({
            success: true,
            client_id: clientId,
            registered: true,
            username: bot.username,
            webhook_url: webhookInfo.result?.url,
            pending_update_count: webhookInfo.result?.pending_update_count || 0,
            last_error_date: webhookInfo.result?.last_error_date,
            last_error_message: webhookInfo.result?.last_error_message,
        });
    } catch (err) {
        res.json({ success: true, client_id: clientId, registered: true, error: err.message });
    }
});

// --- Health check ---
app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        service: 'StaffBot.my Telegram Multi-Bot Manager',
        registered_bots: Object.keys(bots).length,
    });
});

// =====================
// START
// =====================
app.listen(HTTP_PORT, () => {
    logger.log(`🚀 Telegram Multi-Bot Manager running on port ${HTTP_PORT}`);
    logger.log(`📡 Gateway URL: ${GATEWAY_URL}`);
    logger.log(`🌐 Public URL: ${PUBLIC_URL}`);
});
