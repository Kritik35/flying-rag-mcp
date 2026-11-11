import tempfile, lancedb, pyarrow as pa

with tempfile.TemporaryDirectory() as tmpdir:
    db = lancedb.connect(tmpdir)
    schema = pa.schema([
        pa.field("vector", pa.list_(pa.float32(), 4)),
        pa.field("chunk_id", pa.string()),
        pa.field("source_path", pa.string()),
    ])
    records = [
        {"vector": [0.1, 0.2, 0.3, 0.4], "chunk_id": "c1", "source_path": r"C:\FolderA\СП 7.13130.docx"},
        {"vector": [0.1, 0.2, 0.3, 0.4], "chunk_id": "c2", "source_path": r"C:\FolderB\СП 7.13130.docx"},
        {"vector": [0.1, 0.2, 0.3, 0.4], "chunk_id": "c3", "source_path": r"C:\Docs\O'Reilly's Guide.pdf"},
        {"vector": [0.1, 0.2, 0.3, 0.4], "chunk_id": "c4", "source_path": r'C:\НТД\"СП 7.13130.2013" ред. 2.pdf'},
    ]
    tbl = db.create_table("test_table", data=records, schema=schema)
    
    for r in records:
        sp = r["source_path"]
        safe_sp = sp.replace("'", "''")
        where = f"source_path = '{safe_sp}'"
        res = tbl.search().where(where, prefilter=True).to_list()
        print("Target:", repr(sp))
        print("  Where:", where)
        print("  Matches:", [m["chunk_id"] for m in res])
        assert [m["chunk_id"] for m in res] == [r["chunk_id"]], f"Mismatch for {sp}"

print("All exact source_path assertions PASSED!")
