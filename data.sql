select distinct
  a.user_id,
  a.base_date,
  a.collection_score,
  a.collection_score_grade,
  b.v4_bin,
  b.sum_trans_amt_w_1m,
  b.sum_trans_cnt_credit_w_6m,
  b.sum_balance_changes_w_3m,
  b.latest_util_pct,
  b.req_cnt_w_1y,
  b.req_cnt_w_3m,
  b.bnpl_max_od_w_1y,
  b.bnpl_od_15_inv_cnt_w_6m,
  b.bnpl_od_inv_amt_w_3m,
  b.bnpl_days_since_last_ontime_inv,
  b.bnpl_days_since_last_extension,
  b.credit_max_od_w_3m,
  b.bnpl_usage_cnt_w_1y,
  b.bnpl_usage_amt_w_3m,
  b.bnpl_usage_avg_amt_w_3m,
  b.loan_days_since_last_usage,
  b.app_open_cnt_w_1w,
  case when c.overdue_days >= 31 then 1 else 0 end as event
from toki_data_proc_user.collection_bnpl_result a
inner join toki_data_proc_user.collection_bnpl_raw b on a.user_id = b.user_id and a.base_date = b.base_date
inner join toki.bnpl_receivable c on a.user_id = c.account_id and to_char(trunc(a.base_date) + 25, 'YYYYMMDD') = c.p_date
where a.base_date < to_date(:aged_before, 'YYYY-MM-DD')