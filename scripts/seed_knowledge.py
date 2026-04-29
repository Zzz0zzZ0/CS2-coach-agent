"""
战术知识库种子脚本 —— 向 Milvus 注入 CS2 战术知识文档。
用法: python scripts/seed_knowledge.py
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 确保从项目根目录加载 .env
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

from langchain_community.embeddings import DashScopeEmbeddings
from langchain_milvus import Milvus
from langchain_core.documents import Document

# ============================================================
# 硬核 CS2 战术种子数据（顶级分析师视角）
# ============================================================
CS2_TACTICAL_DOCS = [
    Document(
        page_content=(
            "[Mirage A区防守 - CT Default Setup] "
            "标准CT防守A区需构建两层交叉火力（Crossfire）：主防站位于警家（Jungle），副防巡逻跳台（Ticket Booth）。"
            "当T方尝试A1爆弹（A Ramp Execute）时，警家守角CT需第一时间卡住Short角防止A1被快速清场；"
            "跳台CT负责压制A主道（A Main）的挤压推进。"
            "标准防守Util配置：警家一颗HE+燃烧弹（Molotov）封A1出口，Cross区顶楼甩一颗Flashbang致盲入场T。"
            "若T方给出VIP烟雾（Jungle smoke）断视野后执行爆弹，CT须立即启动Retake预案："
            "A包点CT后退至CT通道（CT Spawn）等待主队Retake集结，Anchor one player at site until tradeouts are confirmed。"
            "禁忌动作：在信息真空时从警家Dry-peek A主道，极易被预瞄吃掉导致2换0劣势。"
        ),
        metadata={"map": "Mirage", "side": "CT", "tactic_type": "Default Defensive Setup & Retake"}
    ),
    Document(
        page_content=(
            "[Inferno 香蕉道（Banana）争夺 - T方默认流程与CT反清] "
            "T方开局默认抢占香蕉道控制权的标准序列（Default Banana Take）："
            "Round start即向树位（Tree/Logs）投掷燃烧弹（Incendiary）驱逐前顶CT；"
            "随后一人进入半墙（Half-wall）位与沙袋（Sandbags）位构成交叉压制，逼迫CT退守Banana尽头。"
            "CT方反制（Counter-take）：需两人配合，一人从B包点（B Site）门洞抛出高闪（Pop-flash），"
            "另一人在闪光爆出同时Peek半墙，利用对方致盲窗口完成First Blood争夺。"
            "CT若放弃香蕉控制权缩回B包点，T方将把烟雾落在棺材（Car）、警家（CT）、B门三点，"
            "形成完整Exec压制：进场后Anchor一人守棺材交叉角，主推强行清Car背板和B门警家位。"
            "数据参考：职业赛事中，Inferno CT方在Banana被完全放弃后，B包点Retake成功率仅约31%。"
        ),
        metadata={"map": "Inferno", "side": "Both", "tactic_type": "Map Control & Utility Exec"}
    ),
    Document(
        page_content=(
            "[Dust2 中路控制与A/B分割进攻（Mid Split）] "
            "T方中路控制的核心在于Xbox烟（X-box smoke）配合门烟（Doors smoke）安全穿越中路。"
            "过中后兵分两路执行Split：一路从A小道（Short）爆A区（需Short烟+CT家烟封堵回防），"
            "另一路绕B中门（Mid-to-B）从隧道上方强下B区，利用CT双向拉扯无法同时兼顾的信息差完成爆弹。"
            "时间节点是关键：Xbox烟必须在Round开始后≤5秒落地，否则CT有足够时间前压中路抢占优势角。"
            "CT反制：可安排一人Middle Doors卡窗口，以AWP点杀过中T；主防B区CT须提前感知中出方向，"
            "避免在B Long与Short两路夹击下陷入1v2的Crossfire困境。"
            "Lurk战术补充：T方可留一人在A Long假装施压牵制CT注意力，为Split主攻方向创造时间差。"
        ),
        metadata={"map": "Dust2", "side": "T", "tactic_type": "Mid Control & Split Execute"}
    ),
    Document(
        page_content=(
            "[Nuke 外场（Outside）控制与上下包夹（Vertical Split）] "
            "Nuke的核心地图控制逻辑在于外场（Outside）与Ramp的双重压制。"
            "T方夺取外场后可选择通过Season（外场楼梯）进入上包（Upper Site），"
            "或绕行Ramp下压Lower Site，形成CT需要同时兼顾上下两层的Vertical Split困境。"
            "职业标准Util序列（T侧）：外场Molotov清Heaven位（Squeaky门正上方），"
            "Smoke封锁Hut视野，Flashbang从Outside墙面反弹致盲Yard区CT后再强进Ramp。"
            "CT防守要点：必须在T方拿到外场控制前完成Ramp断前（通常2人组合利用Ramp入口角）。"
            "若外场失守，退守原则：Upper守角ST（Squeaky-to-电话亭）交叉，Lower保持Trophy-Lockers"
            " crossfire，绝对禁止单人从Ramp干探，否则必遭Trade击杀。"
            "核心数据：Nuke上包在外场完全失控情形下，CT Retake胜率不足25%，属于高风险被动态势。"
        ),
        metadata={"map": "Nuke", "side": "Both", "tactic_type": "Vertical Control & Site Split"}
    ),
    Document(
        page_content=(
            "[Ancient B区慢推（Slow Play）与Lurk接应策略] "
            "Ancient地图B区慢推（Slow Play）是高Elo对局中极为主流的消耗策略。"
            "T方一名Lurker提前卡住中路会议室（Cave），通过信息骚扰牵制CT回防节奏；"
            "其余四人在B区逐步推进，利用Donut（圆形通道）与B门的双向进攻路径制造选择压力。"
            "关键道具：B主道进场需提前给出遮蔽CT包点（Site）视野的烟雾，覆盖CT进场角与Pillar后站位；"
            "一颗Molotov精准落在B包点中央可有效拆散CT的交叉火力（Crossfire）站位。"
            "CT侧应对：B区Anchor需维持Pillar交叉—禁止贴墙单线防守，必须与支援位形成夹角。"
            "当Cave方向出现压力信号时，CT必须依赖Radio（语音纪律）传递信息，"
            "确认Lurk位置后方可动用人数优势Flank包抄，否则盲目Rotate将暴露A区空档。"
            "数据参考：职业赛事中Ancient B区慢推战术的爆弹成功率约为42%，高于全图平均水平。"
        ),
        metadata={"map": "Ancient", "side": "T", "tactic_type": "Slow Methodical Push & Lurk Support"}
    ),
]


def seed_milvus_db() -> None:
    collection_name = "cs2_tactical_knowledge"
    milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
    milvus_token = os.getenv("MILVUS_TOKEN", "")

    print(f"=== [战术知识库初始化] 目标: Milvus @ {milvus_uri} ===")

    # 初始化 DashScope Embeddings
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("ERROR: 未找到 DASHSCOPE_API_KEY，请检查 .env 配置文件。")
        sys.exit(1)

    embeddings = DashScopeEmbeddings(
        model="text-embedding-v2",
        dashscope_api_key=api_key
    )

    # 通过 LangChain Milvus 封装直接写入
    print(f"-> 正在向量化并写入 {len(CS2_TACTICAL_DOCS)} 条战术文档到 Collection '{collection_name}' ...")

    try:
        vectorstore = Milvus.from_documents(
            documents=CS2_TACTICAL_DOCS,
            embedding=embeddings,
            connection_args={
                "uri": milvus_uri,
                "token": milvus_token,
            },
            collection_name=collection_name,
            drop_old=True,  # 清空旧数据后重建
            auto_id=True,
        )
        print(f"\n✅ 战术知识库初始化成功，共写入 {len(CS2_TACTICAL_DOCS)} 条记录。")
        print("Advanced RAG 模块弹药装填完毕，等待 Webhook 实战唤醒。")
    except Exception as e:
        print(f"\n❌ 写入 Milvus 失败: {e}")
        print("请确保 Milvus 服务已启动且 .env 中的 MILVUS_URI 配置正确。")
        sys.exit(1)


if __name__ == "__main__":
    seed_milvus_db()
