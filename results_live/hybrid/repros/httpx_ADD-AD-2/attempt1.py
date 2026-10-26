import asyncio
import httpx

async def main() -> None:
    response = httpx.Response(200)
    response.next()  # DOC-LITERAL
    response.anext()  # DOC-LITERAL

asyncio.run(main())
