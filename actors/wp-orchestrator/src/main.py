import asyncio
from apify import Actor

async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        Actor.log.info(f"Input: {actor_input}")
        # TODO: implement agent loop

if __name__ == '__main__':
    asyncio.run(main())
