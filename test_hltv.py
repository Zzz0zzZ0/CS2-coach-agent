import asyncio

async def probe():
    from hltv_async_api import Hltv

    hltv = Hltv()
    print("Fetching recent results...")
    try:
        # Get recent results
        results = await hltv.get_results(days=3, min_rating=1, max=3)
        print("Results:")
        for r in results:
            print(r)
            
            # Let's check the first one with a demo
            if r.get("id"):
                print(f"Fetching match info for {r['id']}...")
                match_info = await hltv.get_match_info(r['id'])
                print(match_info)
                break
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(probe())
