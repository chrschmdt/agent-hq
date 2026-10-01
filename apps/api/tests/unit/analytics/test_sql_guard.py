from __future__ import annotations

import pytest

from ahq.analytics import RejectedSql, guard_readonly_sql

ALLOWED = [
    "select * from retail.orders",
    "SELECT status, count(*) FROM retail.orders GROUP BY status",
    "select carrier, avg(case when status = 'delivered' then 1 else 0 end) from retail.shipments group by 1",
    "with late as (select * from retail.shipments where status = 'in_transit') select count(*) from late",
    "with a as (select 1 as x), b as (select x from a) select * from b",
    "select o.order_id from retail.orders o join retail.shipments s on s.order_id = o.order_id limit 5",
    "select * from support.tickets where created_at > now() - interval '7 days'",
    "select day, value from kpi.daily where metric = 'late_delivery_rate' order by day desc",
    "select a.order_id from retail.orders a union select b.order_id from retail.shipments b",
    "select order_id from retail.orders except select order_id from retail.shipments",
    "select count(distinct user_id) from retail.orders",
    "select date_trunc('day', created_at), count(*) from support.tickets group by 1",
    "select * from retail.orders where order_id in (select order_id from retail.refunds)",
    "select coalesce(sum(amount), 0) from retail.refunds",
    "select t.intent, percentile_cont(0.5) within group (order by t.csat) from support.tickets t group by 1",
    "select * from retail.orders o where exists (select 1 from retail.shipments s where s.order_id = o.order_id)",
    "select lower(subject) from support.tickets",
    "select * from retail.orders order by order_id desc limit 10000",
    "  select 1  ",
    "select * from Retail.Orders",
]

REFUSED = [
    ("select 1; select 2", "exactly one"),
    ("insert into retail.orders values (1)", "Only SELECT"),
    ("update retail.orders set status = 'x'", "Only SELECT"),
    ("delete from retail.orders", "Only SELECT"),
    ("drop table retail.orders", "Only SELECT"),
    ("truncate retail.orders", "Only SELECT"),
    ("alter table retail.orders add column x int", "Only SELECT"),
    ("create table retail.x as select 1", "Only SELECT"),
    ("copy retail.orders to '/tmp/x'", "Only SELECT"),
    ("set statement_timeout = 0", "Only SELECT"),
    ("with d as (delete from retail.orders returning *) select * from d", "Only SELECT"),
    ("select * into scratch from retail.orders", "SELECT INTO"),
    ("select * from retail.orders for update", "Locking"),
    ("select pg_sleep(10)", "pg_sleep"),
    ("select pg_read_file('/etc/passwd')", "pg_read_file"),
    ("select set_config('role', 'postgres', true)", "set_config"),
    ("select current_setting('server_version')", "current_setting"),
    ("select nextval('retail.seq')", "nextval"),
    ("select dblink('host=x', 'select 1')", "dblink"),
    ("select lo_import('/etc/passwd')", "lo_import"),
    ("select * from orders", "Qualify orders"),
    ("select * from ops.work_items", "schema ops"),
    ("select * from agents.tool_calls_audit", "schema agents"),
    ("select * from pg_catalog.pg_roles", "schema pg_catalog"),
    ("select * from information_schema.tables", "schema information_schema"),
    ("select * from public.checkpoints", "schema public"),
    ("select * from (", "does not parse at line 1"),
    ("select * from retail.orders where", "does not parse"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_plain_reads_pass_with_a_limit(sql: str) -> None:
    guarded = guard_readonly_sql(sql, max_rows=50)
    assert guarded.startswith("SELECT * FROM (")
    assert guarded.endswith(") AS q LIMIT 50")


@pytest.mark.parametrize(("sql", "reason"), REFUSED)
def test_everything_else_is_refused_with_a_reason(sql: str, reason: str) -> None:
    with pytest.raises(RejectedSql, match=reason):
        guard_readonly_sql(sql)
