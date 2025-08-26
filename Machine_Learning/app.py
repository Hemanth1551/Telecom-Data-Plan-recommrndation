# app.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from io import StringIO

st.set_page_config(layout="wide", page_title="Telecom Plan Recommender")

####### ---------- Helper functions ----------

@st.cache_data
def load_data(path="customers.csv"):
    df = pd.read_csv(path)
    # basic cleaning: strip column names
    df.columns = [c.strip() for c in df.columns]
    return df

def build_plan_catalog(df):
    """
    Derive a plan catalog from existing rows by taking median plan attributes.
    Returns DataFrame with one row per plan and columns:
    plan, data_limit_gb, call_limit_min, sms_limit, monthly_bill
    """
    plan_cols = ['current_plan', 'data_limit_gb', 'call_limit_min', 'sms_limit', 'monthly_bill']
    plans = df[plan_cols].groupby('current_plan').median().reset_index()
    plans = plans.rename(columns={'current_plan':'plan_id',
                                  'monthly_bill':'plan_price'})
    # use nicer column order
    plans = plans[['plan_id','data_limit_gb','call_limit_min','sms_limit','plan_price']]
    return plans

def score_user_plan(user_row, plan_row):
    """
    Compute a fit score (0..5) for how well `plan_row` fits `user_row`.
    Combines usage-fit (data/calls/sms) and cost-fit.
    """
    # avoid division by zero
    eps = 1e-9
    # utilization ratios
    data_util = user_row['monthly_usage_gb'] / (plan_row['data_limit_gb'] + eps)
    call_util = user_row['monthly_calls_min'] / (plan_row['call_limit_min'] + eps)
    sms_util  = user_row['monthly_sms'] / (plan_row['sms_limit'] + eps)

    # fit measure: ideal utilization ~1.0 => fit = 1 - abs(util - 1)
    def fit_from_util(u):
        fit = 1 - abs(u - 1)
        # clamp to -1..1 then normalize to 0..1
        fit = max(-1.0, min(1.0, fit))
        return (fit + 1) / 2.0

    f_data = fit_from_util(data_util)
    f_call = fit_from_util(call_util)
    f_sms  = fit_from_util(sms_util)

    usage_fit = (f_data + f_call + f_sms) / 3.0  # 0..1

    # cost fit: prefer plans that are <= current bill or not much higher
    # cost_ratio = plan_price / user_bill
    cost_ratio = plan_row['plan_price'] / (user_row['monthly_bill'] + eps)
    if cost_ratio <= 1.0:
        cost_fit = 1.0  # cheaper or equal price -> good
    else:
        # penalize proportionally; mapping to (0..1]
        cost_fit = 1.0 / cost_ratio
        cost_fit = max(0.0, min(1.0, cost_fit))

    # final score: weight usage fit higher than cost (tweakable)
    final = 0.65 * usage_fit + 0.35 * cost_fit  # 0..1
    # scale to 0..5 rating-like
    return round(final * 5, 3), {
        'data_util': round(data_util,3),
        'call_util': round(call_util,3),
        'sms_util': round(sms_util,3),
        'usage_fit': round(usage_fit,3),
        'cost_fit': round(cost_fit,3)
    }

def recommend_for_user(user_row, plans_df, k=3):
    scores = []
    for _, plan in plans_df.iterrows():
        score, meta = score_user_plan(user_row, plan)
        scores.append({
            'plan_id': plan['plan_id'],
            'plan_price': plan['plan_price'],
            'data_limit_gb': plan['data_limit_gb'],
            'call_limit_min': plan['call_limit_min'],
            'sms_limit': plan['sms_limit'],
            'score': score,
            **meta
        })
    scored = pd.DataFrame(scores).sort_values('score', ascending=False).reset_index(drop=True)
    return scored.head(k)

def generate_recommendations_for_all(df, plans_df, k=3):
    rows = []
    for _, user in df.iterrows():
        recs = recommend_for_user(user, plans_df, k)
        for rank, r in recs.head(k).iterrows():
            rows.append({
                'customer_id': user['customer_id'],
                'name': user.get('name', ""),
                'age': user.get('age', ""),
                'current_plan': user['current_plan'],
                'monthly_usage_gb': user['monthly_usage_gb'],
                'monthly_calls_min': user['monthly_calls_min'],
                'monthly_sms': user['monthly_sms'],
                'monthly_bill': user['monthly_bill'],
                'recommended_plan_id': r['plan_id'],
                'recommended_plan_price': r['plan_price'],
                'recommended_plan_data_limit_gb': r['data_limit_gb'],
                'recommended_plan_call_limit_min': r['call_limit_min'],
                'recommended_plan_sms_limit': r['sms_limit'],
                'recommendation_score': r['score'],
                'data_util': r['data_util'],
                'call_util': r['call_util'],
                'sms_util': r['sms_util']
            })
    return pd.DataFrame(rows)

####### ---------- App ----------

st.title("📡 Telecom Data Plan Recommendation — (ML + Dashboard)")

# Layout: left sidebar for upload/selection, main content for visuals
with st.sidebar:
    st.header("Dataset")
    uploaded = st.file_uploader("Upload `customers.csv` (or use existing file)", type=["csv"])
    use_sample = st.checkbox("Use sample bundled dataset (customers.csv)", value=True if uploaded is None else False)
    top_k = st.slider("Top K recommendations", min_value=1, max_value=5, value=3)

# Load dataset (either uploaded or default file)
if uploaded is not None:
    df = pd.read_csv(uploaded)
else:
    # attempt to read local customers.csv
    try:
        df = load_data("customers.csv")
    except Exception as e:
        st.error("No dataset found. Upload a CSV with the required columns or place 'customers.csv' in this folder.")
        st.stop()

# quick checks
required_cols = {'customer_id','monthly_usage_gb','monthly_calls_min','monthly_sms','current_plan','data_limit_gb','call_limit_min','sms_limit','monthly_bill'}
if not required_cols.issubset(set(df.columns)):
    st.error(f"Dataset missing required columns. Required: {sorted(required_cols)}")
    st.write("Your columns:", df.columns.tolist())
    st.stop()

# build plan catalog derived from data
plans_df = build_plan_catalog(df)

# select user
st.sidebar.header("Inspect a Customer")
customer_select = st.sidebar.selectbox("Choose customer (id or name)", options=df['customer_id'].tolist())
selected_user = df[df['customer_id'] == customer_select].iloc[0]

# Main area: user summary + recommendations
col1, col2 = st.columns([1.2, 1])

with col1:
    st.subheader("Customer Summary")
    st.markdown(f"**Name:** {selected_user.get('name', '')}  \n"
                f"**Customer ID:** {selected_user['customer_id']}  \n"
                f"**Age:** {selected_user.get('age', '')}  \n"
                f"**Current Plan:** {selected_user['current_plan']}  \n"
                f"**Monthly Usage:** {selected_user['monthly_usage_gb']} GB  \n"
                f"**Monthly Calls:** {selected_user['monthly_calls_min']} min  \n"
                f"**Monthly SMS:** {selected_user['monthly_sms']}  \n"
                f"**Monthly Bill:** ₹{selected_user['monthly_bill']}  \n")

    st.write("**Current Plan Limits (median from dataset)**")
    cur_plan = plans_df[plans_df['plan_id'] == selected_user['current_plan']]
    if not cur_plan.empty:
        cur_plan = cur_plan.iloc[0]
        st.write({
            'data_limit_gb': cur_plan['data_limit_gb'],
            'call_limit_min': cur_plan['call_limit_min'],
            'sms_limit': cur_plan['sms_limit'],
            'plan_price': cur_plan['plan_price']
        })
    else:
        st.info("Current plan details not found in the derived catalog.")

    st.write("---")
    st.subheader("Top Recommendations")
    recs = recommend_for_user(selected_user, plans_df, k=top_k)
    # show readable table
    show_cols = ['plan_id','plan_price','data_limit_gb','call_limit_min','sms_limit','score']
    st.dataframe(recs.rename(columns={'plan_id':'plan','plan_price':'price','score':'score (0-5)'}).round(3))

with col2:
    st.subheader("Usage vs Plan Comparison (Selected Customer)")
    # bar chart: usage vs selected plan and top recommended plan
    # prepare a comparison table
    comp_rows = []
    # current plan
    cur_row = plans_df[plans_df['plan_id'] == selected_user['current_plan']]
    if not cur_row.empty:
        cur = cur_row.iloc[0]
        comp_rows.append({
            'label':'Current plan (' + selected_user['current_plan'] + ')',
            'data_limit_gb': cur['data_limit_gb'],
            'call_limit_min': cur['call_limit_min'],
            'monthly_bill': cur['plan_price']
        })
    # top rec
    top_rec = recs.iloc[0]
    comp_rows.append({
        'label':'Top Recommendation (' + top_rec['plan_id'] + ')',
        'data_limit_gb': top_rec['data_limit_gb'],
        'call_limit_min': top_rec['call_limit_min'],
        'monthly_bill': top_rec['plan_price']
    })
    # actual usage as a separate row
    comp_rows.append({
        'label':'Actual Usage',
        'data_limit_gb': selected_user['monthly_usage_gb'],
        'call_limit_min': selected_user['monthly_calls_min'],
        'monthly_bill': selected_user['monthly_bill']
    })
    comp_df = pd.DataFrame(comp_rows)

    fig1 = px.bar(comp_df, x='label', y=['data_limit_gb','call_limit_min'], barmode='group',
                  title="Plan Limits vs Actual Usage (data in GB / calls in min)")
    st.plotly_chart(fig1, use_container_width=True)

    fig2 = px.bar(comp_df, x='label', y=['monthly_bill'], title="Plan Price vs Actual Bill (₹)")
    st.plotly_chart(fig2, use_container_width=True)

# Analyst section: aggregated recommendations and ability to export
st.markdown("---")
st.header("Analyst View — Bulk Recommendations & Exports")
st.write("Derived plan catalog (one row per plan):")
st.dataframe(plans_df)

# generate recommendations for all users
if st.button("Generate recommendations for all users and show top result"):
    all_recs = generate_recommendations_for_all(df, plans_df, k=top_k)
    # show best recommendation (rank 1) per user
    best_per_user = all_recs.sort_values(['customer_id','recommendation_score'], ascending=[True,False]).groupby('customer_id').first().reset_index()
    st.subheader("Best recommendation per user (summary)")
    st.dataframe(best_per_user[['customer_id','name','current_plan','recommended_plan_id','recommended_plan_price','recommendation_score']].round(3))

    # Download button for full recommendations (top-k rows per user)
    csv_full = all_recs.to_csv(index=False)
    st.download_button("Download full recommendations (CSV)", csv_full, "recommendations_full.csv", "text/csv")

    # Also save to local file for backend to read (optional)
    try:
        all_recs.to_csv("recommendations.csv", index=False)
        st.success("Saved recommendations.csv to local folder (backend can consume this file).")
    except Exception as e:
        st.warning("Could not save locally (permission issue?). You can still download the CSV above.")

# Option to upload new CSV to re-run (admin)
st.markdown("---")
st.header("Admin: Upload new dataset / replace")
uploaded_new = st.file_uploader("Upload new customers CSV to replace dataset (optional)", type=["csv"], key="admin_upload")
if uploaded_new is not None:
    new_df = pd.read_csv(uploaded_new)
    st.success("New dataset uploaded. Please restart app to use the new file as default or click 'Generate recommendations' to run on this dataset in-memory.")
    st.dataframe(new_df.head())

st.markdown("---")
st.caption("How frontend/backend can use the output: the app writes `recommendations.csv` (customer_id, name, current_plan, recommended_plan_id, recommended_plan_price, recommendation_score, ...). Backend can read that CSV or you can create a small endpoint to serve recommendations as JSON.")
