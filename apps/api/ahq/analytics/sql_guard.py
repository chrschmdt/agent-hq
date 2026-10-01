from __future__ import annotations

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from ahq.domain import AhqError

ALLOWED_SCHEMAS = frozenset({"retail", "support", "kpi"})
DENIED_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
DENIED_FUNCTIONS = frozenset(
    {"set_config", "current_setting", "nextval", "setval", "currval", "query_to_xml", "table_to_xml", "cursor_to_xml"}
)
WRITES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Set,
)
DEFAULT_MAX_ROWS = 200


class RejectedSql(AhqError):
    pass


def guard_readonly_sql(sql: str, *, max_rows: int = DEFAULT_MAX_ROWS) -> str:
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="postgres") if statement is not None]
    except ParseError as error:
        raise RejectedSql(_parse_problem(error)) from error
    if len(statements) != 1:
        raise RejectedSql("Send exactly one statement.")
    query = statements[0]
    if not isinstance(query, exp.Select | exp.SetOperation):
        raise RejectedSql("Only SELECT queries are allowed.")
    if any(isinstance(node, WRITES) for node in query.walk()):
        raise RejectedSql("Only SELECT queries are allowed.")
    for select in query.find_all(exp.Select):
        if select.args.get("into"):
            raise RejectedSql("SELECT INTO creates a table; select the rows instead.")
        if select.args.get("locks"):
            raise RejectedSql("Locking clauses such as FOR UPDATE are not allowed.")
    for function in query.find_all(exp.Func):
        name = (function.name if isinstance(function, exp.Anonymous) else function.sql_name()).lower()
        if name in DENIED_FUNCTIONS or name.startswith(DENIED_PREFIXES):
            raise RejectedSql(f"The function {name} is not allowed.")
    _check_tables(query)
    wrapped = exp.select("*").from_(query.subquery("q")).limit(max_rows)
    return wrapped.sql(dialect="postgres")


def _parse_problem(error: ParseError) -> str:
    details = error.errors[0] if error.errors else {}
    description = str(details.get("description") or "unexpected text").split(" but got ")[0]
    description = re.sub(r"<class '[\w.]*\.(\w+)'>", r"\1", description)
    where = f" at line {details.get('line')}, column {details.get('col')}" if details.get("line") else ""
    return f"The query does not parse{where}: {description}."


def _check_tables(query: exp.Select | exp.SetOperation) -> None:
    ctes = {cte.alias_or_name.lower() for cte in query.find_all(exp.CTE)}
    for table in query.find_all(exp.Table):
        schema = table.db.lower()
        if not schema:
            if table.name.lower() in ctes:
                continue
            raise RejectedSql(f"Qualify {table.name} with its schema, for example retail.orders.")
        if table.catalog or schema not in ALLOWED_SCHEMAS:
            raise RejectedSql(f"The schema {table.db} is not available; query retail, support or kpi.")
