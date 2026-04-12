import requests
import json
import uuid

# 构造一个极度逼真的高层次 CS2 赛后数据载荷，故意模拟 Mirage A 区的失守
payload = {
    "match_id": f"pro-match-{uuid.uuid4().hex[:8]}",
    "map_name": "Mirage",
    "rounds": [
        {
            "round_number": 1,
            "winner": "T",
            "win_type": "Bomb Exploded",
            "events": [
                {"time": "1:20", "type": "utility", "player": "T_Support", "item": "Smoke", "target": "Jungle", "success": True},
                {"time": "1:18", "type": "utility", "player": "T_Support", "item": "Flashbang", "target": "A Ramp Popflash", "success": True},
                {"time": "1:15", "type": "kill", "killer": "T_Entry", "victim": "CT_Jungle", "weapon": "AK47", "location": {"killer": "A Ramp", "victim": "Jungle (Blind)"}},
                {"time": "1:12", "type": "kill", "killer": "T_Entry", "victim": "CT_Ticket", "weapon": "AK47", "location": {"killer": "Tetris", "victim": "Ticket Booth"}},
                {"time": "1:10", "type": "bomb_planted", "planter": "T_IGL", "site": "A"}
            ],
            "economy": {"T_start": 3500, "CT_start": 4000}
        },
        {
            "round_number": 2,
            "winner": "T",
            "win_type": "Terrorists Win",
            "events": [
                {"time": "1:35", "type": "kill", "killer": "T_Lurker", "victim": "CT_Mid", "weapon": "AK47", "location": {"killer": "Top Mid", "victim": "Connector"}},
                {"time": "1:00", "type": "utility", "player": "T_Support", "item": "Smoke", "target": "CT Spawn", "success": True},
                {"time": "0:55", "type": "kill", "killer": "T_Entry", "victim": "CT_Firebox", "weapon": "Galil", "location": {"killer": "Palace", "victim": "Firebox"}},
                {"time": "0:45", "type": "bomb_planted", "planter": "T_IGL", "site": "A"}
            ],
            "economy": {"T_start": 12500, "CT_start": 1800}
        }
    ],
    "extra_data": {
        "platform": "FACEIT",
        "avg_elo": 3400,
        "region": "EU"
    },
    "team_score": {"CT": 0, "T": 2} # 该字段会被 Pydantic 的 model_extra "allow" 规则捕获
}

def test_webhook():
    url = "http://127.0.0.1:8000/api/webhook/match-end"
    print(f"🚀 发起端到端流转测试 -> POST {url}")
    print(">>> 模拟 Payload (Mirage A区防守崩溃局):")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    
    try:
        # 发送 POST 请求并设置超时时间，防止同步阻塞过长
        response = requests.post(url, json=payload, timeout=5)
        print("\n=== HTTP 响应结果 ===")
        print(f"Status Code: {response.status_code}")
        print(f"Response Body: {response.text}")
        
        if response.status_code == 200:
            print("\n✅ Webhook 请求畅通，服务器已接收并抛入后台！")
            print("查看启动了 FastAPI 服务的控制台日志，观察 LangGraph 和大模型的推演过程，")
            print("或稍后查阅 output/analysis.log 的更新。")
        else:
            print(f"\n❌ 请求失败，服务端返回异常状态码。")
            
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接被拒决！请确保你已经在另外一个终端通过 `python main.py` 启动了 FastAPI 服务！")
    except Exception as e:
        print(f"\n❌ 发生了预料外的异常: {e}")

if __name__ == "__main__":
    test_webhook()
