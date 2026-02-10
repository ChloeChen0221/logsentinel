import asyncio
import httpx

async def test_loki():
    url = "http://localhost:3102/loki/api/v1/query_range"
    params = {
        "query": '{namespace="demo"}',
        "limit": "5"
    }
    
    # 尝试不同的配置
    configs = [
        {"http2": False},
        {"http2": False, "headers": {"User-Agent": "python-httpx"}},
        {"http2": True},
    ]
    
    for i, config in enumerate(configs):
        print(f"\n=== Test {i+1}: {config} ===")
        async with httpx.AsyncClient(timeout=10, **config) as client:
            try:
                response = await client.get(url, params=params)
                print(f"Status: {response.status_code}")
                if response.status_code == 200:
                    data = response.json()
                    print(f"Success: {data.get('status')}")
                    print(f"Results: {len(data.get('data', {}).get('result', []))}")
                    return  # 成功就退出
                else:
                    print(f"Error: {response.text[:100]}")
            except Exception as e:
                print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_loki())
