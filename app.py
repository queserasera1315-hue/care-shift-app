import streamlit as st
import pandas as pd
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# ---------------------------------------------------------
# 1. ページ基本設定（スマホ表示向け最適化）
# ---------------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成", layout="centered")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("条件を指定して「シフトを作成する」ボタンを押してください。")

# ---------------------------------------------------------
# 2. スマホから操作する条件入力フォーム
# ---------------------------------------------------------
st.subheader("⚙️ 1. 基本条件の設定")

# スタッフ名の入力
staff_input = st.text_input(
    "スタッフ名（カンマ区切りで入力）", 
    value="Aさん, Bさん, Cさん, Dさん, Eさん"
)
staffs = [s.strip() for s in staff_input.split(",") if s.strip()]

# 作成日数の選択
num_days = st.number_input("作成日数（日）", min_value=1, max_value=31, value=7)
days = list(range(1, num_days + 1))

# 各シフトの必要人数の設定
st.subheader("👥 2. 1日あたりの必要人数")
col1, col2 = st.columns(2)
with col1:
    req_hayaban = st.number_input("早番", min_value=0, value=1)
    req_nikkin = st.number_input("日勤", min_value=0, value=1)
with col2:
    req_osoban = st.number_input("遅番", min_value=0, value=1)
    req_yakin = st.number_input("夜勤", min_value=0, value=1)

# シフト一覧
shifts = ["早", "日", "遅", "夜", "休"]

# ---------------------------------------------------------
# 3. シフト計算ロジック（ボタン押下時に実行）
# ---------------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    with st.spinner("AIが最適なシフトを計算中..."):
        
        # 数理モデルの定義
        prob = LpProblem("ShiftScheduling", LpMinimize)
        x = {}
        for s in staffs:
            for d in days:
                for shift in shifts:
                    x[s, d, shift] = LpVariable(f"x_{s}_{d}_{shift}", cat="Binary")

        # 制約1: 各スタッフは1日1シフト
        for s in staffs:
            for d in days:
                prob += lpSum([x[s, d, shift] for shift in shifts]) == 1

        # 制約2: 夜勤明けの翌日は「休」
        for s in staffs:
            for d in days[:-1]:
                prob += x[s, d, "夜"] + x[s, d + 1, "休"] >= 2 * x[s, d, "夜"]

        # 制約3: 必要人数の確保
        for d in days:
            prob += lpSum([x[s, d, "早"] for s in staffs]) >= req_hayaban
            prob += lpSum([x[s, d, "日"] for s in staffs]) >= req_nikkin
            prob += lpSum([x[s, d, "遅"] for s in staffs]) >= req_osoban
            prob += lpSum([x[s, d, "夜"] for s in staffs]) >= req_yakin

        # 目的関数: 夜勤数の平準化（全体の夜勤数を最小化）
        prob += lpSum([x[s, d, "夜"] for s in staffs for d in days])

        # 計算実行
        status = prob.solve()

        # ---------------------------------------------------------
        # 4. 結果の画面表示・ダウンロード機能
        # ---------------------------------------------------------
        if LpStatus[status] == "Optimal":
            st.success("✅ シフト表を作成しました！")
            
            result_data = {}
            for s in staffs:
                s_shifts = []
                for d in days:
                    for shift in shifts:
                        if value(x[s, d, shift]) == 1:
                            s_shifts.append(shift)
                result_data[s] = s_shifts
            
            # 表を作成して表示
            df = pd.DataFrame(result_data, index=[f"{d}日" for d in days]).T
            st.dataframe(df, use_container_width=True)
            
            # CSVダウンロードボタン（Excel等で開く用）
            csv = df.to_csv().encode('utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv,
                file_name="シフト表.csv",
                mime="text/csv"
            )
        else:
            st.error("❌ 条件を満たすシフトを作成できませんでした。スタッフ数を増やすか、必要人数を減らして再試行してください。")
