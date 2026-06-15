import sys, asyncio
sys.path.insert(0, '/app')
from app.database import async_session_factory
from app.services.gateway_config_service import build_gateway_config, push_config_to_gateway

async def main():
    async with async_session_factory() as db:
        config = await build_gateway_config(db)
        cps = config.get('custom_providers', [])
        print('Providers:', [p['name'] for p in cps])
        m = config['model']
        print('Primary:', m['provider'], '->', m['default'])
        ok = await push_config_to_gateway(config)
        print('Push to gateway:', 'OK' if ok else 'FAIL')

asyncio.run(main())
