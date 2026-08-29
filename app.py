import streamlit as st
import pandas as pd
from pulp import LpProblem, LpVariable, LpMinimize, lpSum, LpStatus, value

# ---------------------------------------------------------
# 1. ページ基本設定
# ---------------------------------------------------------
st.set_page_config(page_title="介護シフト自動作成", layout="centered")
st.title("🏥 介護シフト自動作成アプリ")
st.caption("個別スキル、個別連勤上限、遅早防止、夜勤サイクルを考慮してシフトを作成します。")

# ---------------------------------------------------------
# 2. 基本条件の設定
# ---------------------------------------------------------
st.subheader("⚙️ 1. 基本条件の設定")

staff_input = st.text_input(
    "スタッフ名（カンマ区切り）", 
    value="Aさん, Bさん, Cさん, Dさん, Eさん, Fさん"
)
staffs = [s.strip() for s in staff_input.split(",") if s.strip()]

num_days = st.number_input("作成日数（日）", min_value=1, max_value=31, value=30)
days = list(range(1, num_days + 1))

# 公休数の設定
monthly_holidays = st.number_input("1人あたりの純粋な公休数（日）", min_value=1, max_value=15, value=9)

# ---------------------------------------------------------
# 3. 1日あたりの必要人数
# ---------------------------------------------------------
st.subheader("👥 2. 1日あたりの必要人数")
col1, col2 = st.columns(2)
with col1:
    req_hayaban = st.number_input("早番 (7-16)", min_value=0, value=1)
    req_nikkin = st.number_input("日勤 (9-18)", min_value=0, value=1)
with col2:
    req_osoban = st.number_input("遅番 (10-19)", min_value=0, value=1)
    req_yakin = st.number_input("夜勤 (16-9)", min_value=0, value=1)

shifts = ["早", "日", "遅", "夜", "明", "休"]

# ---------------------------------------------------------
# 4. スタッフごとの個別条件設定
# ---------------------------------------------------------
st.subheader("👤 3. スタッフごとの個別条件設定")

staff_roles = {}
max_consecutive_days = {}
desire_holidays = {}

# 定義可能な可能シフトパターン
role_options = {
    "全シフト可（早/遅/日/夜）": ["早", "日", "遅", "夜", "明", "休"],
    "日勤帯のみ（早/遅/日）": ["早", "日", "遅", "休"],
    "夜勤専用（夜）": ["夜", "明", "休"],
    "早・日のみ": ["早", "日", "休"],
    "遅・日のみ": ["遅", "日", "休"]
}

for s in staffs:
    with st.expander(f"【{s}】の設定", expanded=True):
        # 可能シフト選択
        role_choice = st.selectbox(
            "勤務可能なシフト", 
            options=list(role_options.keys()), 
            key=f"role_{s}"
        )
        staff_roles[s] = role_options[role_choice]

        # 最大連勤数
        max_work = st.number_input(
            "最大連勤数（日）", 
            min_value=2, 
            max_value=7, 
            value=5, 
            key=f"max_work_{s}"
        )
        max_consecutive_days[s] = max_work

        # 希望休
        holiday_str = st.text_input(
            "希望休（日付をカンマ区切りで入力 例: 5, 12）", 
            value="", 
            key=f"holiday_{s}"
        )
        parsed_days = []
        for d_str in holiday_str.split(","):
            d_str = d_str.strip()
            if d_str.isdigit():
                d_num = int(d_str)
                if 1 <= d_num <= num_days:
                    parsed_days.append(d_num)
        desire_holidays[s] = parsed_days

# ---------------------------------------------------------
# 5. シフト計算ロジック
# ---------------------------------------------------------
st.markdown("---")

if st.button("🚀 シフトを作成する", type="primary"):
    with st.spinner("AIが全制約を満たすシフトを計算中..."):
        
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

        # 制約2: 可能シフトのみ割り振る
        for s in staffs:
            allowed_shifts = staff_roles[s]
            for d in days:
                for shift in shifts:
                    if shift not in allowed_shifts:
                        prob += x[s, d, shift] == 0

        # 制約3: 夜勤(16-9) ➔ 翌日「明」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "明"] >= x[s, d, "夜"]

        # 制約4: 「明」 ➔ 翌日「休」
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "休"] >= x[s, d, "明"]

        # 制約5: 遅番 ➔ 翌日「早番」の禁止（遅早禁止）
        for s in staffs:
            for d in range(1, num_days):
                prob += x[s, d + 1, "早"] + x[s, d, "遅"] <= 1

        # 制約6: スタッフごとの最大連勤数制限
        for s in staffs:
            k = max_consecutive_days[s]
            # k+1日間のうち、公休（休）が最低1日は入るようにする（明は勤務扱い）
            for d in range(1, num_days - k + 1):
                prob += lpSum([x[s, d + i, "休"] for i in range(k + 1)]) >= 1

        # 制約7: 公休数は「休」の回数のみでカウント
        for s in staffs:
            prob += lpSum([x[s, d, "休"] for d in days]) == monthly_holidays

        # 制約8: 希望休の反映
        for s in staffs:
            for d in desire_holidays[s]:
                prob += x[s, d, "休"] == 1

        # 制約9: 必要人数の確保
        for d in days:
            prob += lpSum([x[s, d, "早"] for s in staffs]) >= req_hayaban
            prob += lpSum([x[s, d, "日"] for s in staffs]) >= req_nikkin
            prob += lpSum([x[s, d, "遅"] for s in staffs]) >= req_osoban
            prob += lpSum([x[s, d, "夜"] for s in staffs]) >= req_yakin

        # 目的関数: 夜勤回数の平準化
        prob += lpSum([x[s, d, "夜"] for s in staffs for d in days])

        # 計算実行
        status = prob.solve()

        # ---------------------------------------------------------
        # 6. 結果表示
        # ---------------------------------------------------------
        if LpStatus[status] == "Optimal":
            st.success("✅ すべての個別制約・遅早禁止を満たしたシフト表を作成しました！")
            
            result_data = {}
            for s in staffs:
                s_shifts = []
                for d in days:
                    for shift in shifts:
                        if value(x[s, d, shift]) == 1:
                            s_shifts.append(shift)
                result_data[s] = s_shifts
            
            df = pd.DataFrame(result_data, index=[f"{d}日" for d in days]).T
            st.dataframe(df, use_container_width=True)
            
            csv = df.to_csv().encode('utf-8-sig')
            st.download_button(
                label="📥 CSVでダウンロード",
                data=csv,
                file_name="シフト表.csv",
                mime="text/csv"
            )
        else:
            st.error("❌ 条件を満たすシフトを作成できませんでした。日勤のみの人が多くて夜勤枠が埋まらない、あるいは連勤上限や希望休が厳しすぎる可能性があります。")
