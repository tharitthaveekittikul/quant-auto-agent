# This file is kept as a usage example.
# The actual implementation lives in adapters/projectx/.
#
# Example: stream real-time quotes from TopstepX
#
#   import asyncio
#   from adapters import ProjectXClient, Environment
#
#   async def main():
#       client = await ProjectXClient.from_env()  # reads PROJECTX_ENV/USERNAME/API_KEY
#       accounts = await client.rest.search_accounts()
#       account_id = accounts[0]["id"]
#
#       await client.connect_market(
#           ["CON.F.US.MES.M25"],
#           on_quote=lambda cid, data: print(f"{cid}: bid={data['bestBid']} ask={data['bestAsk']}"),
#       )
#       await client.connect_user(account_id, on_order=lambda d: print("Order:", d))
#
#       await asyncio.sleep(3600)  # run for 1 hour
#       await client.disconnect()
#
#   asyncio.run(main())
