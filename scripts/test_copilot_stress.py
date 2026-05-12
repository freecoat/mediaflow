"""
test_copilot_stress.py — E2E copilot test su dataset stress.

Test pattern:
1. Ping Claude API (auth check)
2. 3 clienti casuali (filmografia) → query AI sul cliente
3. 3 progetti casuali → query AI su quote
4. 3 plannings (= job con bookings) → query AI su pianificazione

Output: docs/copilot_test_report.md con domande/risposte + nomi entità testate.
"""
from __future__ import annotations
import sys
import json
import random
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.models import (
    User, Client, ClientWork, Project, ProjectStatus, Job, JobStatus,
    AIConversation, AIMessage, Booking, BookingAssignment, JobResourceAssignment,
)
from app.services.ai_provider import get_provider_for_user
from app.services.ai_assistant import build_system_prompt
from app.services.ai_loop import advance_loop

random.seed(7)


def banner(t):
    print("\n" + "=" * 70)
    print(f"  {t}")
    print("=" * 70)


def main():
    db = SessionLocal()
    admin = db.query(User).filter(User.email == "admin@mediaflow.it").first()
    if not admin:
        print("FATAL: admin@mediaflow.it not found")
        return
    print(f"Admin: {admin.email} (id={admin.id})")

    provider = get_provider_for_user(admin.id, db)
    if provider is None:
        print("FATAL: nessun AI provider configurato per admin")
        return
    print(f"Provider: {provider.name} model={getattr(provider, 'model', 'n/a')}")

    # ── 1. Ping rapido ──
    banner("PING — auth check Claude API")
    try:
        reply = provider.chat(
            [{"role": "user", "content": "Rispondi con 'OK' (una parola)."}],
            max_tokens=20, temperature=0,
        )
        print(f"Risposta: {reply!r}")
        ping_ok = "OK" in (reply or "").upper()
    except Exception as e:
        print(f"PING FAILED: {e}")
        ping_ok = False
        return

    report_sections = []
    report_sections.append(f"# Copilot E2E Test Report")
    report_sections.append(f"\n_Generato {datetime.now().isoformat(timespec='seconds')}_")
    report_sections.append(f"\nProvider: **{provider.name}** model `{getattr(provider, 'model', 'n/a')}`")
    report_sections.append(f"\nPing API: {'OK ✓' if ping_ok else 'FAIL ✗'}")

    # ── 2. 3 clienti casuali con filmografia ricca ──
    banner("CLIENTI — 3 query su filmografie")
    # prefer clienti con >= 5 works
    clients_with_works = (
        db.query(Client)
        .join(ClientWork)
        .group_by(Client.id)
        .all()
    )
    # filter a quelli con >=5 opere
    def n_works(c): return len(c.works)
    rich = [c for c in clients_with_works if n_works(c) >= 5]
    random.shuffle(rich)
    sample_clients = rich[:3] if len(rich) >= 3 else clients_with_works[:3]

    client_results = []
    for c in sample_clients:
        works = c.works[:5]
        titles = ", ".join(f"{w.title} ({w.year})" for w in works)
        question = (
            f"Riassumi in 3-4 righe il cliente '{c.name}' (sede: {c.city}, {c.country}). "
            f"Dimmi se vedi pattern interessanti nella sua filmografia: {titles}"
        )
        conv = AIConversation(user_id=admin.id, title=f"Test cliente {c.name}")
        db.add(conv); db.commit(); db.refresh(conv)
        system = build_system_prompt(db, use_tools=True, page="/clients")
        try:
            res = advance_loop(db, conv, provider, system, user_message=question,
                               initial_messages=[])
            ans = (res.get("text") or "").strip()[:600]
            client_results.append({"client": c.name, "city": c.city, "question": question, "answer": ans})
            print(f"\n→ {c.name}")
            print(f"  Q: {question[:120]}")
            print(f"  A: {ans[:300]}")
        except Exception as e:
            client_results.append({"client": c.name, "city": c.city, "question": question, "answer": f"ERROR: {e}"})
            print(f"  ERROR: {e}")

    report_sections.append("\n## Test 1 — Filmografie clienti\n")
    for r in client_results:
        report_sections.append(f"### {r['client']} ({r['city']})")
        report_sections.append(f"**Q:** {r['question']}\n")
        report_sections.append(f"**A:** {r['answer']}\n")

    # ── 3. 3 progetti con quote ──
    banner("PROGETTI — 3 query su quotazioni")
    # Prefer projects with active quote
    from app.models import Quote, QuoteStatus
    proj_with_quote = (
        db.query(Project)
        .join(Quote)
        .filter(Quote.status == QuoteStatus.approved)
        .group_by(Project.id)
        .limit(50)
        .all()
    )
    random.shuffle(proj_with_quote)
    sample_projects = proj_with_quote[:3]

    project_results = []
    for p in sample_projects:
        question = (
            f"Per il progetto '{p.title}' (codice {p.code}, tipologia {p.project_type}, "
            f"deliverable {p.delivery_format}), riassumi in 4 righe il quadro: "
            f"durata, formato, deadline. Suggerisci 2 voci chiave del listino tipiche."
        )
        conv = AIConversation(user_id=admin.id, project_id=p.id,
                              title=f"Test progetto {p.code}")
        db.add(conv); db.commit(); db.refresh(conv)
        system = build_system_prompt(db, use_tools=True, project_id=p.id, page="/projects")
        try:
            res = advance_loop(db, conv, provider, system, user_message=question,
                               initial_messages=[])
            ans = (res.get("text") or "").strip()[:600]
            project_results.append({"code": p.code, "title": p.title, "question": question, "answer": ans})
            print(f"\n→ {p.code} — {p.title}")
            print(f"  A: {ans[:300]}")
        except Exception as e:
            project_results.append({"code": p.code, "title": p.title, "question": question, "answer": f"ERROR: {e}"})
            print(f"  ERROR: {e}")

    report_sections.append("\n## Test 2 — Progetti con quote\n")
    for r in project_results:
        report_sections.append(f"### {r['code']} — {r['title']}")
        report_sections.append(f"**Q:** {r['question']}\n")
        report_sections.append(f"**A:** {r['answer']}\n")

    # ── 4. 3 plannings (job con bookings) ──
    banner("PIANIFICAZIONI — 3 query su scheduling")
    jobs_with_bookings = (
        db.query(Job)
        .join(Booking)
        .group_by(Job.id)
        .limit(60)
        .all()
    )
    random.shuffle(jobs_with_bookings)
    sample_jobs = jobs_with_bookings[:3]

    planning_results = []
    for job in sample_jobs:
        n_bookings = db.query(Booking).filter(Booking.job_id == job.id).count()
        n_assignments = (
            db.query(BookingAssignment)
            .join(Booking, BookingAssignment.booking_id == Booking.id)
            .filter(Booking.job_id == job.id).count()
        )
        n_resources = db.query(JobResourceAssignment).filter(
            JobResourceAssignment.job_id == job.id
        ).count()
        question = (
            f"Per il job '{job.title}' (codice {job.code}) ci sono {n_bookings} booking "
            f"con {n_assignments} assegnazioni e {n_resources} risorse contrattualmente "
            f"allocate. Periodo {job.start_date} → {job.end_date}. "
            f"Dimmi se la pianificazione sembra ben distribuita o se vedi rischi."
        )
        conv = AIConversation(user_id=admin.id, job_id=job.id,
                              project_id=job.project_id,
                              title=f"Test planning {job.code}")
        db.add(conv); db.commit(); db.refresh(conv)
        system = build_system_prompt(db, use_tools=True,
                                     project_id=job.project_id, job_id=job.id,
                                     page="/planning")
        try:
            res = advance_loop(db, conv, provider, system, user_message=question,
                               initial_messages=[])
            ans = (res.get("text") or "").strip()[:600]
            planning_results.append({
                "job_code": job.code, "job_title": job.title,
                "n_bookings": n_bookings, "n_assignments": n_assignments,
                "question": question, "answer": ans,
            })
            print(f"\n→ {job.code} — {job.title}")
            print(f"  Bookings: {n_bookings}, Assignments: {n_assignments}, Resources: {n_resources}")
            print(f"  A: {ans[:300]}")
        except Exception as e:
            planning_results.append({
                "job_code": job.code, "job_title": job.title,
                "n_bookings": n_bookings, "n_assignments": n_assignments,
                "question": question, "answer": f"ERROR: {e}",
            })
            print(f"  ERROR: {e}")

    report_sections.append("\n## Test 3 — Pianificazioni (job + bookings)\n")
    for r in planning_results:
        report_sections.append(f"### {r['job_code']} — {r['job_title']}")
        report_sections.append(f"_{r['n_bookings']} booking, {r['n_assignments']} assignments_\n")
        report_sections.append(f"**Q:** {r['question']}\n")
        report_sections.append(f"**A:** {r['answer']}\n")

    # ── Summary ──
    report_sections.append("\n## Riepilogo entità testate\n")
    report_sections.append("| Categoria | Nome | Note |")
    report_sections.append("|-----------|------|------|")
    for r in client_results:
        report_sections.append(f"| Cliente | {r['client']} | {r['city']} |")
    for r in project_results:
        report_sections.append(f"| Progetto | {r['title']} | {r['code']} |")
    for r in planning_results:
        report_sections.append(f"| Planning (Job) | {r['job_title']} | {r['job_code']} — {r['n_bookings']} booking |")

    out = ROOT / "docs" / "copilot_test_report.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(report_sections), encoding="utf-8")
    print(f"\nReport -> {out}")
    db.close()


if __name__ == "__main__":
    main()
