import sys
sys.path.insert(0, '/app')
import asyncio
from app.database import get_session
from app.services.gateway_config_service import build_gateway_config, push_config_to_gateway

async def main():
    async with get_session() as db:
        config = await build_gateway_config(db)
        cps = config.get('custom_providers', [])
        print('Providers:', [p['name'] for p in cps])
        m = config['model']
        print('Primary:', m['provider'], '->', m['default'])
        ok = await push_config_to_gateway(config)
        print('Push:', 'OK' if ok else 'FAIL')

asyncio.run(main())
