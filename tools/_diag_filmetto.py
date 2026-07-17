import sqlite3, sys, json
con = sqlite3.connect(r"C:\Users\frico\OneDrive\Documents\Claude\Projects\mediaflow_fase1bis\mediaflow.db")
cur = con.cursor()

print("=== PROJECT/JOB Filmetto ===")
cur.execute("""
  SELECT p.id, p.code, p.title, j.id, j.code, j.title, j.weighted_revenue
  FROM projects p
  LEFT JOIN jobs j ON j.project_id = p.id
  WHERE p.title LIKE '%ilmetto%' OR p.code LIKE '%ilmetto%'
     OR (j.title LIKE '%ilmetto%' OR j.code LIKE '%ilmetto%')
""")
projects = cur.fetchall()
for r in projects:
    print(r)

if not projects:
    print("(nessun match Filmetto)")
    sys.exit(0)

job_ids = sorted({r[3] for r in projects if r[3] is not None})
print(f"\nJob IDs: {job_ids}")

for jid in job_ids:
    print(f"\n=== JCL job_id={jid} ===")
    cur.execute("""
      SELECT id, description, unit, unit_price, quantity_quoted, quantity_actual,
             qty_planned, total_quoted, total_accrued, total_expected
      FROM job_cost_lines
      WHERE job_id = ?
      ORDER BY id
    """, (jid,))
    cols = ["id","desc","unit","up","qq","qa","qp","tq","tac","texp"]
    rows = cur.fetchall()
    for r in rows:
        d = dict(zip(cols, r))
        d["desc"] = (d["desc"] or "")[:55]
        print(json.dumps(d, ensure_ascii=False))

    print(f"\n=== Quote lines for job_id={jid} ===")
    cur.execute("""
      SELECT ql.id, ql.description, ql.unit, ql.unit_price, ql.quantity
      FROM quotes q
      JOIN quote_lines ql ON ql.quote_id = q.id
      WHERE q.id IN (SELECT quote_id FROM jobs WHERE id = ?)
      ORDER BY ql.id
    """, (jid,))
    for r in cur.fetchall():
        print(r[:2], "unit=", r[2], "up=", r[3], "qty=", r[4])

    print(f"\n=== Bookings linked to job {jid} ===")
    cur.execute("""
      SELECT b.id, b.job_cost_line_id, b.start_datetime, b.end_datetime,
             b.resource_id, b.execution_status
      FROM bookings b
      WHERE b.job_id = ?
      ORDER BY b.start_datetime
    """, (jid,))
    for r in cur.fetchall():
        print(r)
