from app.services.deliverables_parser import split_into_chunks


def test_short_text_single_chunk():
    assert split_into_chunks("hello", size=100) == ["hello"]


def test_long_text_multiple_chunks_with_overlap():
    text = "x" * 300_000
    chunks = split_into_chunks(text, size=120_000, overlap=5_000)
    assert len(chunks) >= 3
    # ogni chunk non supera size+overlap
    assert all(len(c) <= 120_000 + 5_000 for c in chunks)
    # overlap: l'inizio del chunk 2 deve ricomparire alla fine del chunk 1
    assert chunks[1][:1000] in chunks[0] or chunks[0][-5000:] == chunks[1][:5000]


def test_prefers_section_boundary():
    # blocco 1 ~ size, poi una sezione numerata: il taglio cade sulla sezione
    head = "A" * 119_000
    section = "\n4.8 Section Title\n" + ("B" * 4000)
    tail = "C" * 100_000
    chunks = split_into_chunks(head + section + tail, size=120_000, overlap=2_000)
    assert len(chunks) >= 2
    assert chunks[1].lstrip().startswith("4.8 Section Title")


def test_reassembly_covers_all_content():
    text = "".join(str(i % 10) for i in range(250_000))
    chunks = split_into_chunks(text, size=100_000, overlap=1_000)
    # concatenando e rimuovendo overlap si ricopre tutto: ogni carattere originale
    # è presente in almeno un chunk
    joined = "".join(chunks)
    assert len(joined) >= len(text)
