import copy
import time
import ipaddress

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# =====================================================================
# ネットワーク・トポロジー定義
# =====================================================================
# 各ルータのインタフェース定義
# type: "LAN"（端末が繋がるネットワーク） / "LINK"（ルータ間リンク）
# peer: LINK の場合、接続先ルータ名
IFACES = {
    "R1": {
        "eth0": {"ip": "192.168.1.1", "subnet": "192.168.1.0/24", "type": "LAN", "peer": None},
        "eth1": {"ip": "10.0.12.1", "subnet": "10.0.12.0/30", "type": "LINK", "peer": "R2"},
        "eth2": {"ip": "10.0.13.1", "subnet": "10.0.13.0/30", "type": "LINK", "peer": "R3"},
    },
    "R2": {
        "eth0": {"ip": "192.168.2.1", "subnet": "192.168.2.0/24", "type": "LAN", "peer": None},
        "eth1": {"ip": "10.0.12.2", "subnet": "10.0.12.0/30", "type": "LINK", "peer": "R1"},
        "eth2": {"ip": "10.0.23.1", "subnet": "10.0.23.0/30", "type": "LINK", "peer": "R3"},
    },
    "R3": {
        "eth0": {"ip": "192.168.3.1", "subnet": "192.168.3.0/24", "type": "LAN", "peer": None},
        "eth1": {"ip": "10.0.23.2", "subnet": "10.0.23.0/30", "type": "LINK", "peer": "R2"},
        "eth2": {"ip": "10.0.34.1", "subnet": "10.0.34.0/30", "type": "LINK", "peer": "R4"},
        "eth3": {"ip": "10.0.13.2", "subnet": "10.0.13.0/30", "type": "LINK", "peer": "R1"},
    },
    "R4": {
        "eth0": {"ip": "192.168.4.1", "subnet": "192.168.4.0/24", "type": "LAN", "peer": None},
        "eth1": {"ip": "10.0.34.2", "subnet": "10.0.34.0/30", "type": "LINK", "peer": "R3"},
    },
}

ROUTERS = ["R1", "R2", "R3", "R4"]

# next_hop の IP からその IP を持つルータを引くための辞書
IP_TO_ROUTER = {}
for _r, _ifs in IFACES.items():
    for _name, _info in _ifs.items():
        IP_TO_ROUTER[_info["ip"]] = _r

# ルータ間リンク一覧（描画用）: (routerA, ifaceA, routerB, ifaceB)
LINKS = [
    ("R1", "eth1", "R2", "eth1"),
    ("R1", "eth2", "R3", "eth3"),
    ("R2", "eth2", "R3", "eth1"),
    ("R3", "eth2", "R4", "eth1"),
]

# 初期ルーティングテーブル（意図的に最短経路になっていない箇所を含む）
DEFAULT_TABLES = {
    "R1": [
        {"destination": "192.168.1.0/24", "next_hop": "direct", "interface": "eth0"},
        {"destination": "10.0.12.0/30", "next_hop": "direct", "interface": "eth1"},
        {"destination": "10.0.13.0/30", "next_hop": "direct", "interface": "eth2"},
        {"destination": "192.168.2.0/24", "next_hop": "10.0.12.2", "interface": "eth1"},
        {"destination": "192.168.3.0/24", "next_hop": "10.0.13.2", "interface": "eth2"},
        {"destination": "192.168.4.0/24", "next_hop": "10.0.13.2", "interface": "eth2"},
    ],
    "R2": [
        {"destination": "192.168.2.0/24", "next_hop": "direct", "interface": "eth0"},
        {"destination": "10.0.12.0/30", "next_hop": "direct", "interface": "eth1"},
        {"destination": "10.0.23.0/30", "next_hop": "direct", "interface": "eth2"},
        {"destination": "192.168.1.0/24", "next_hop": "10.0.12.1", "interface": "eth1"},
        {"destination": "192.168.3.0/24", "next_hop": "10.0.23.2", "interface": "eth2"},
        {"destination": "192.168.4.0/24", "next_hop": "10.0.23.2", "interface": "eth2"},
    ],
    "R3": [
        {"destination": "192.168.3.0/24", "next_hop": "direct", "interface": "eth0"},
        {"destination": "10.0.23.0/30", "next_hop": "direct", "interface": "eth1"},
        {"destination": "10.0.34.0/30", "next_hop": "direct", "interface": "eth2"},
        {"destination": "10.0.13.0/30", "next_hop": "direct", "interface": "eth3"},
        {"destination": "192.168.1.0/24", "next_hop": "10.0.13.1", "interface": "eth3"},
        {"destination": "192.168.2.0/24", "next_hop": "10.0.23.1", "interface": "eth1"},
        {"destination": "192.168.4.0/24", "next_hop": "10.0.34.2", "interface": "eth2"},
    ],
    "R4": [
        {"destination": "192.168.4.0/24", "next_hop": "direct", "interface": "eth0"},
        {"destination": "10.0.34.0/30", "next_hop": "direct", "interface": "eth1"},
        {"destination": "192.168.1.0/24", "next_hop": "10.0.34.1", "interface": "eth1"},
        {"destination": "192.168.2.0/24", "next_hop": "10.0.34.1", "interface": "eth1"},
        {"destination": "192.168.3.0/24", "next_hop": "10.0.34.1", "interface": "eth1"},
    ],
}

# 描画用の座標
ROUTER_POS = {
    "R1": (1.0, 5.0),
    "R2": (5.5, 9.0),
    "R3": (5.5, 1.0),
    "R4": (10.0, 5.0),
}
LAN_POS = {
    "R1": (1.0, 8.5),
    "R2": (5.5, 12.3),
    "R3": (5.5, -2.3),
    "R4": (13.5, 5.0),
}

# =====================================================================
# セッション状態の初期化
# =====================================================================
st.set_page_config(page_title="ルーティング体験シミュレーター", layout="wide")

if "tables" not in st.session_state:
    st.session_state.tables = copy.deepcopy(DEFAULT_TABLES)
if "sim" not in st.session_state:
    st.session_state.sim = None
if "auto_play" not in st.session_state:
    st.session_state.auto_play = False


def new_simulation(start_router: str, dest_ip: str):
    st.session_state.sim = {
        "current_router": start_router,
        "start_router": start_router,
        "destination_ip": dest_ip,
        "log": [],
        "visited": [],
        "hops": 0,
        "finished": False,
        "success": None,
        "last_matched": {},
    }


def do_step():
    sim = st.session_state.sim
    if sim is None or sim["finished"]:
        return
    router = sim["current_router"]
    sim["visited"].append(router)
    dest_ip = ipaddress.ip_address(sim["destination_ip"])
    table = st.session_state.tables.get(router, [])

    matches = []
    for row in table:
        dest_str = str(row.get("destination", "")).strip()
        try:
            net = ipaddress.ip_network(dest_str, strict=False)
        except ValueError:
            continue
        if dest_ip in net:
            matches.append((net.prefixlen, row))

    if not matches:
        sim["log"].append(
            f"❌ **{router}**：宛先 `{sim['destination_ip']}` に一致する経路がルーティングテーブルにありません。"
            "パケットは破棄されました（宛先不明）。"
        )
        sim["finished"] = True
        sim["success"] = False
        return

    matches.sort(key=lambda t: -t[0])
    best_prefix, best = matches[0]
    dest_net = str(best.get("destination", "")).strip()
    nh = str(best.get("next_hop", "")).strip()
    iface = str(best.get("interface", "")).strip()
    sim["last_matched"][router] = dest_net

    sim["log"].append(
        f"🔎 **{router}**：宛先 `{sim['destination_ip']}` を検索 → 最長一致は "
        f"`{dest_net}` （/{best_prefix}）→ next-hop=`{nh}`, interface=`{iface}`"
    )

    if nh.lower() == "direct":
        info = IFACES.get(router, {}).get(iface)
        if info is None:
            sim["log"].append(
                f"⚠️ **{router}**：インタフェース `{iface}` は存在しません。設定ミスのためパケットは破棄されました。"
            )
            sim["finished"] = True
            sim["success"] = False
            return
        if info["type"] == "LAN":
            sim["log"].append(
                f"✅ **{router}** の `{iface}`（{info['subnet']}）は宛先が属するネットワークです。"
                "パケットは端末（PC）に届きました！"
            )
        else:
            sim["log"].append(
                f"✅ **{router}** の `{iface}` は直結リンクです。パケットはここで処理されました。"
            )
        sim["finished"] = True
        sim["success"] = True
        return

    try:
        ipaddress.ip_address(nh)
        valid_ip = True
    except ValueError:
        valid_ip = False

    if not valid_ip:
        sim["log"].append(
            f"❌ **{router}**：next-hop `{nh}` はIPアドレスとして不正です。パケットは破棄されました。"
        )
        sim["finished"] = True
        sim["success"] = False
        return

    next_router = IP_TO_ROUTER.get(nh)
    if next_router is None:
        sim["log"].append(
            f"❌ next-hop `{nh}` を持つ機器が見つかりません（設定ミスの可能性）。パケットは迷子になりました。"
        )
        sim["finished"] = True
        sim["success"] = False
        return

    sim["log"].append(f"➡️ **{router}** は `{iface}` からパケットを **{next_router}**（next-hop {nh}）へ転送します。")
    sim["current_router"] = next_router
    sim["hops"] += 1
    if sim["hops"] > 12:
        sim["log"].append("🔁 ホップ数が多すぎます。ループが発生している可能性があるため停止しました。")
        sim["finished"] = True
        sim["success"] = False


# =====================================================================
# ネットワーク図の描画
# =====================================================================
def offset_point(p1, p2, t, perp=0.0):
    x = p1[0] + (p2[0] - p1[0]) * t
    y = p1[1] + (p2[1] - p1[1]) * t
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = (dx ** 2 + dy ** 2) ** 0.5 or 1
    nx, ny = -dy / length, dx / length
    return x + nx * perp, y + ny * perp


def draw_network(sim):
    fig, ax = plt.subplots(figsize=(9.5, 7))
    ax.set_xlim(-2.5, 16)
    ax.set_ylim(-4, 14)
    ax.axis("off")

    current_router = sim["current_router"] if sim else None
    visited = set(sim["visited"]) if sim else set()
    finished = sim["finished"] if sim else False
    success = sim["success"] if sim else None
    dest_ip = sim["destination_ip"] if sim else None

    # 宛先が属する LAN を判定（成功時のハイライト用）
    dest_router = None
    if dest_ip:
        for r, ifs in IFACES.items():
            for info in ifs.values():
                if info["type"] == "LAN":
                    net = ipaddress.ip_network(info["subnet"])
                    try:
                        if ipaddress.ip_address(dest_ip) in net:
                            dest_router = r
                    except ValueError:
                        pass

    # --- ルータ間リンク ---
    # (複数リンクがルータ1台に集中してもラベルが重ならないよう、リンクごとに
    #  中央1箇所へまとめて「サブネットと両端のインタフェース名」だけを表示する。
    #  ネクストホップのIPアドレス自体は表示しない）
    for ra, ifa, rb, ifb in LINKS:
        pa, pb = ROUTER_POS[ra], ROUTER_POS[rb]
        ax.plot([pa[0], pb[0]], [pa[1], pb[1]], color="#8a8a8a", linewidth=2, zorder=1)
        mid = offset_point(pa, pb, 0.5, perp=0.45)
        label = f"{IFACES[ra][ifa]['subnet']}\n{ra}:{ifa} - {rb}:{ifb}"
        ax.text(*mid, label, fontsize=6.3, ha="center", va="center", color="#333333",
                bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="#cccccc", alpha=0.85),
                zorder=3)

    # --- ルータ〜LAN接続 ---
    for r in ROUTERS:
        rp, lp = ROUTER_POS[r], LAN_POS[r]
        ax.plot([rp[0], lp[0]], [rp[1], lp[1]], color="#8a8a8a", linewidth=1.5,
                linestyle="--", zorder=1)

    # --- LAN ボックス ---
    # 宛先IPアドレスが属するネットワークは、パケットが到達する前から常に強調表示する
    for r in ROUTERS:
        lp = LAN_POS[r]
        subnet = IFACES[r]["eth0"]["subnet"]
        is_target = dest_router == r
        reached = finished and success and is_target

        if reached:
            face, edge, lw = "#66bb6a", "#1b5e20", 2.5
        elif is_target:
            face, edge, lw = "#fff59d", "#e65100", 2.5
        else:
            face, edge, lw = "#e8f5e9", "#2e7d32", 1.5

        rect = mpatches.FancyBboxPatch(
            (lp[0] - 1.05, lp[1] - 0.55), 2.1, 1.1,
            boxstyle="round,pad=0.05,rounding_size=0.15",
            facecolor=face, edgecolor=edge, linewidth=lw, zorder=2,
        )
        ax.add_patch(rect)
        label = f"PC\n{subnet}"
        if reached:
            label += "\n[GOAL]"
        elif is_target:
            label += "\n[TARGET]"
        ax.text(lp[0], lp[1], label, fontsize=7, ha="center", va="center", fontweight="bold", zorder=3)

    # --- ルータ本体 ---
    for r in ROUTERS:
        rp = ROUTER_POS[r]
        if r == current_router and not (finished and not success and False):
            face, edge, lw = "#ff9800", "#e65100", 3
        elif r in visited:
            face, edge, lw = "#fff3cd", "#c79100", 2
        else:
            face, edge, lw = "#bbdefb", "#0d47a1", 2
        if finished and success is False and r == current_router:
            face, edge = "#ef9a9a", "#c62828"
        circ = mpatches.Circle(rp, 0.75, facecolor=face, edgecolor=edge, linewidth=lw, zorder=4)
        ax.add_patch(circ)
        ax.text(rp[0], rp[1] + 0.05, r, fontsize=12, fontweight="bold", ha="center", va="center", zorder=5)
        if r == current_router:
            # 絵文字フォントに依存しないよう、パケットはマーカー図形で表現する
            ax.plot(rp[0], rp[1] - 1.2, marker="s", markersize=14,
                    markerfacecolor="#d32f2f", markeredgecolor="#7f0000", zorder=6)
            ax.text(rp[0], rp[1] - 1.2, "PKT", fontsize=5.5, color="white",
                    fontweight="bold", ha="center", va="center", zorder=7)

    ax.set_aspect("equal")
    fig.tight_layout()
    return fig


# =====================================================================
# UI
# =====================================================================
st.title("🌐 ルーティング体験シミュレーター")
st.caption(
    "ルータは「① 宛先IPを見る → ② ルーティングテーブルを参照 → ③ ネクストホップを決定 → ④ 転送する」"
    "という処理を繰り返します。ルーティングテーブルを書き換えると、通信の経路がどう変わるか観察してみましょう。"
)

col_net, col_table = st.columns([3, 2], gap="large")

with col_net:
    st.subheader("📡 ネットワーク図")
    sim = st.session_state.sim
    fig = draw_network(sim)
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    st.subheader("🚀 パケット送信シミュレーション")
    c1, c2 = st.columns(2)
    with c1:
        start_router = st.selectbox("送信元ルータ（PCが接続されている場所）", ROUTERS, key="start_router_select")
    with c2:
        dest_ip_input = st.text_input("宛先IPアドレス", value="192.168.4.10", key="dest_ip_input")

    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("📨 パケット生成", use_container_width=True):
            try:
                ipaddress.ip_address(dest_ip_input.strip())
                new_simulation(start_router, dest_ip_input.strip())
                st.session_state.auto_play = False
            except ValueError:
                st.error("宛先IPアドレスの形式が正しくありません。")
    with b2:
        next_disabled = st.session_state.sim is None or st.session_state.sim["finished"]
        if st.button("⏭️ 次へ（1ホップ進める）", use_container_width=True, disabled=next_disabled):
            do_step()
    with b3:
        auto_disabled = st.session_state.sim is None or st.session_state.sim["finished"]
        st.session_state.auto_play = st.toggle(
            "▶️ 自動実行", value=st.session_state.auto_play, disabled=auto_disabled
        )
    with b4:
        if st.button("🔄 リセット", use_container_width=True):
            st.session_state.sim = None
            st.session_state.auto_play = False
            st.rerun()

    sim = st.session_state.sim
    if sim:
        if sim["finished"]:
            if sim["success"]:
                st.success(f"🎉 パケットは宛先 `{sim['destination_ip']}` に到達しました！（{sim['hops']} ホップ）")
            else:
                st.error(f"⚠️ パケットは宛先 `{sim['destination_ip']}` に届きませんでした。")
        else:
            st.info(f"現在パケットは **{sim['current_router']}** にいます。「次へ」または「自動実行」で処理を進めましょう。")

        st.markdown("#### 📜 パケットの旅ログ")
        if sim["log"]:
            for i, entry in enumerate(sim["log"], start=1):
                st.markdown(f"{i}. {entry}")
        else:
            st.caption("まだログはありません。「次へ」を押して最初のホップを実行してください。")
    else:
        st.caption("「パケット生成」を押してシミュレーションを開始してください。")

with col_table:
    st.subheader("🛠️ ルーティングテーブル編集")
    edit_router = st.selectbox("編集するルータ", ROUTERS, key="edit_router_select")

    with st.expander("🔧 インタフェース一覧（参考）", expanded=False):
        for r in ROUTERS:
            rows = []
            for name, info in IFACES[r].items():
                peer = f" ↔ {info['peer']}" if info["peer"] else "（LAN）"
                rows.append(f"- `{name}`: {info['ip']}（{info['subnet']}）{peer}")
            st.markdown(f"**{r}**\n" + "\n".join(rows))

    df = pd.DataFrame(st.session_state.tables[edit_router])
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"editor_{edit_router}",
        column_config={
            "destination": st.column_config.TextColumn("宛先ネットワーク (CIDR)", help="例: 192.168.4.0/24"),
            "next_hop": st.column_config.TextColumn("ネクストホップ", help="'direct' または IPアドレス"),
            "interface": st.column_config.TextColumn("インタフェース", help="例: eth0"),
        },
    )

    ac1, ac2 = st.columns(2)
    with ac1:
        if st.button("✅ この設定を適用", use_container_width=True):
            cleaned = edited_df.fillna("").to_dict("records")
            errors = []
            for row in cleaned:
                dest = str(row.get("destination", "")).strip()
                if dest == "":
                    continue
                try:
                    ipaddress.ip_network(dest, strict=False)
                except ValueError:
                    errors.append(dest)
            if errors:
                st.error(f"次の宛先ネットワークの形式が正しくありません: {', '.join(errors)}")
            else:
                st.session_state.tables[edit_router] = [
                    row for row in cleaned if str(row.get("destination", "")).strip() != ""
                ]
                st.success(f"{edit_router} のルーティングテーブルを更新しました。")
    with ac2:
        if st.button("↩️ このルータを初期状態に戻す", use_container_width=True):
            st.session_state.tables[edit_router] = copy.deepcopy(DEFAULT_TABLES[edit_router])
            editor_key = f"editor_{edit_router}"
            if editor_key in st.session_state:
                del st.session_state[editor_key]
            st.rerun()

    st.markdown("#### 現在このルータで使われているテーブル")
    st.dataframe(pd.DataFrame(st.session_state.tables[edit_router]), use_container_width=True, hide_index=True)

# --- 自動実行 ---
if st.session_state.auto_play and st.session_state.sim and not st.session_state.sim["finished"]:
    time.sleep(1.3)
    do_step()
    st.rerun()
