"""F1 pipeline deliverables (v3.5.0-alpha.172.135) — bucketing capitolato→listino.

Riduce un ``DeliveryItem`` (menù completo di specs tecniche) a una voce di
listino GENERICA riusabile (bucket). Molti DeliveryItem → una voce. Scope:
ridurre all'osso il numero di voci + uniformità.

`compute_bucket(db, item)` ramifica per media_kind (decisione 11 della spec
docs/superpowers/specs/2026-05-29-deliverables-pipeline-design.md):
- video    → (package|container) + codec + risoluzione + HDR
- audio    → mix_type/role + channel_config (traccia primaria = sort_order minore)
- subtitle/key/disc/document → per tipo container

`match_or_create_bucket()` trova-o-crea il PriceItem corrispondente (match per
``name`` entro la categoria "Deliveries") e ci linka l'item via
``suggested_price_item_id`` (riuso del campo come link canonico, decisione 9).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import (
    DeliveryItem, AudioTrackSpec, PriceItem,
    Package, Container, VideoCodec, Resolution,
    AudioMixType, AudioChannelConfig,
)

# media_kind del container → gruppo bucket. "mixed" (QuickTime/MXF) risolto a
# runtime: video se ha codec video, audio se solo tracce audio.
_SIDECAR_KINDS = {"subtitle", "key", "disc", "document"}

# HDR token che NON entrano nel nome (= nessuna lavorazione HDR dedicata).
_NO_HDR = {"", "SDR", "NONE"}


@dataclass
class BucketSpec:
    """Voce-bucket derivata da un DeliveryItem."""
    group: str            # video | audio | subtitle | key | disc | document | other
    label: str            # nome leggibile = chiave naturale di match
    keywords: list[str] = field(default_factory=list)


def _name(db: Session, model, fk: Optional[int]) -> Optional[str]:
    if not fk:
        return None
    rec = db.get(model, fk)
    return rec.name if rec else None


def _media_group(db: Session, item: DeliveryItem) -> str:
    """Determina il gruppo bucket di un item dalla taxonomy."""
    # Un package di consegna (DCP/IMF) è sempre una forma video.
    if item.package_id:
        return "video"
    container = db.get(Container, item.container_id) if item.container_id else None
    mk = (container.media_kind if container else None) or ""
    if mk in _SIDECAR_KINDS:
        return mk
    if mk == "audio":
        return "audio"
    if mk == "image_seq":
        return "video"
    if mk == "mixed":
        # QuickTime/MXF: video se ha codec video, altrimenti audio se ha tracce.
        if item.video_codec_id:
            return "video"
        if _has_audio_tracks(db, item):
            return "audio"
        return "video"
    # Nessun container/package noto: ricade su tracce audio se presenti.
    if _has_audio_tracks(db, item):
        return "audio"
    return "other"


def _has_audio_tracks(db: Session, item: DeliveryItem) -> bool:
    return db.execute(
        select(AudioTrackSpec.id).where(AudioTrackSpec.delivery_item_id == item.id).limit(1)
    ).first() is not None


def _primary_audio_track(db: Session, item: DeliveryItem) -> Optional[AudioTrackSpec]:
    """Traccia con sort_order minore (la principale del deliverable)."""
    return db.execute(
        select(AudioTrackSpec)
        .where(AudioTrackSpec.delivery_item_id == item.id)
        .order_by(AudioTrackSpec.sort_order, AudioTrackSpec.id)
        .limit(1)
    ).scalars().first()


def _hdr_token(item: DeliveryItem) -> Optional[str]:
    h = (item.hdr_format or "").strip()
    return None if h.upper() in _NO_HDR else h


def _join(parts: list[Optional[str]]) -> str:
    return " / ".join(p for p in parts if p)


def compute_bucket(db: Session, item: DeliveryItem) -> BucketSpec:
    """Riduce un DeliveryItem alla sua voce-bucket di listino."""
    group = _media_group(db, item)

    if group == "audio":
        tr = _primary_audio_track(db, item)
        mix = _name(db, AudioMixType, tr.mix_type_id) if tr else None
        chan = _name(db, AudioChannelConfig, tr.channel_config_id) if tr else None
        label = _join([mix or "Audio", chan])
        return BucketSpec(group="audio", label=label,
                          keywords=_kw(["audio", mix, chan]))

    if group in _SIDECAR_KINDS:
        label = _name(db, Container, item.container_id) or group.capitalize()
        return BucketSpec(group=group, label=label, keywords=_kw([group, label]))

    if group == "video":
        form = _name(db, Package, item.package_id) or _name(db, Container, item.container_id)
        codec = _name(db, VideoCodec, item.video_codec_id)
        res = _name(db, Resolution, item.resolution_id)
        hdr = _hdr_token(item)
        label = _join([form, codec, res, hdr]) or (item.name or "Deliverable")
        return BucketSpec(group="video", label=label,
                          keywords=_kw(["video", form, codec, res, hdr]))

    # other: fallback sul nome dell'item, senza esplodere.
    return BucketSpec(group="other", label=item.name or "Deliverable",
                      keywords=_kw(["deliverable", item.name]))


def _kw(parts) -> list[str]:
    """Token lowercase unici per ricerca, scartando None/vuoti."""
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        t = str(p).strip().lower()
        if t and t not in out:
            out.append(t)
    return out


def match_or_create_bucket(
    db: Session, tenant_id: int, item: DeliveryItem, category_id: int,
    *, default_unit: str = "pc",
) -> PriceItem:
    """Trova-o-crea il PriceItem bucket per ``item`` nella categoria data.

    Match per ``(tenant_id, category_id, name)``. Non committa: il chiamante
    (migrazione/endpoint) controlla la transazione.
    """
    spec = compute_bucket(db, item)
    existing = db.execute(
        select(PriceItem).where(
            PriceItem.tenant_id == tenant_id,
            PriceItem.category_id == category_id,
            PriceItem.name == spec.label,
        ).limit(1)
    ).scalars().first()
    if existing:
        return existing

    unit = (item.suggested_unit or default_unit).strip() or default_unit
    pi = PriceItem(
        tenant_id=tenant_id,
        category_id=category_id,
        name=spec.label,
        description=f"Bucket consegna generico ({spec.group}).",
        unit=unit,
        keywords=spec.keywords or None,
        is_active=True,
    )
    db.add(pi)
    db.flush()  # popola pi.id senza commit
    return pi


def template_bucket_options(db: Session, tenant_id: int, template_id: int) -> list[dict]:
    """Sorgente del picker quote (decisione 10): le voci-bucket distinte presenti
    fra i DeliveryItem del template, derivate live (non da ``suggested_items``).

    Per ogni bucket ritorna prezzo listino + quanti/quali DeliveryItem ci mappano
    + una proposta di ``detail`` (note di capitolato aggregate) da incollare nella
    riga di quote. Ordinato per nome bucket. Salta item senza link a una voce
    attiva.
    """
    items = db.execute(
        select(DeliveryItem).where(
            DeliveryItem.tenant_id == tenant_id,
            DeliveryItem.delivery_template_id == template_id,
            DeliveryItem.is_active == True,  # noqa: E712
            DeliveryItem.suggested_price_item_id.isnot(None),
        )
    ).scalars().all()
    if not items:
        return []

    # Raggruppa per voce-bucket.
    by_pi: dict[int, list[DeliveryItem]] = {}
    for it in items:
        by_pi.setdefault(it.suggested_price_item_id, []).append(it)

    price_items = {
        p.id: p for p in db.execute(
            select(PriceItem).where(
                PriceItem.id.in_(by_pi.keys()),
                PriceItem.tenant_id == tenant_id,
                PriceItem.is_active == True,  # noqa: E712
            )
        ).scalars().all()
    }

    out: list[dict] = []
    for pid, group in by_pi.items():
        pi = price_items.get(pid)
        if not pi:  # voce inattiva/cancellata → salta
            continue
        # v3.5.0-alpha.172.146 — detail_suggestion ricco: prima conteneva SOLO
        # le note (spesso vuote → detail vuoto in quote). Ora aggrega le specs
        # tecniche risolte (label bucket per-item: codec/res/HDR o mix/canali),
        # i nomi capitolato originali e le note — tutto distinto, ordine stabile.
        detail_parts: list[str] = []

        def _push(v: Optional[str]):
            v = (v or "").strip()
            if v and v not in detail_parts:
                detail_parts.append(v)

        for it in group:
            spec = compute_bucket(db, it)
            # label specs solo se aggiunge info rispetto al nome bucket (pi.name)
            if spec.label and spec.label != pi.name:
                _push(spec.label)
            _push(it.name)
            _push(it.notes)
        out.append({
            "price_item_id": pi.id,
            "name": pi.name,
            "unit": pi.unit,
            "price_list": pi.price_list,
            "price_average": pi.price_average,
            "price_low": pi.price_low,
            "item_count": len(group),
            "item_names": [it.name for it in group],
            # v3.5.0-alpha.172.161 — id+nome dei DeliveryItem del bucket, per
            # consentire al picker quote di fissare il "punto di partenza" delle
            # tech specs (QuoteLine.delivery_item_id). Ordine = stabile per id.
            "items": [{"id": it.id, "name": it.name} for it in sorted(group, key=lambda x: x.id)],
            "detail_suggestion": " · ".join(detail_parts) if detail_parts else None,
        })
    out.sort(key=lambda o: o["name"].lower())
    return out
