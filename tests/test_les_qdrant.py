import os
import sys
from rag_server.tools import search_documents
import json

def main():
    print("Testing search_documents with use_les_db=True...")
    try:
        results = search_documents(
            query="вентиляция",
            top_k=3,
            debug=True,
            use_les_db=True
        )
        print("Results:")
        print(json.dumps(results, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
