from app.database import SessionLocal
from app.services.ai_assistant import _h_read_quote_lines

db = SessionLocal()
try:
    r = _h_read_quote_lines(db, {"quote_number": "Q-2026-008-v4"})
    print("counts:", r["counts"])
    print("--- consegne (deliverable) ---")
    tot_qty = 0.0
    for ln in r["lines"]:
        if ln["nature"] != "consegna":
            continue
        q = ln["quantity"] or 0
        tot_qty += q
        sec = f" [{ln['section_label']}]" if ln.get("section_label") else ""
        print(f"  {ln['position']} | {ln['description']}{sec} | qty {q} {ln['unit']}")
    print(f"--- somma quantità consegne: {tot_qty}")
finally:
    db.close()
