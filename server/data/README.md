# server/data

Grounding corpus for the kiosk assistant, loaded by [`server/knowledge.py`](../knowledge.py).

- `mari_energies_knowledge_base.md` — Mari Energies Limited knowledge base, converted from
  the source `MariEnergies_RAG_Knowledge_Base_V2.docx`. Retrieval keys off `##`/`###`
  headings, so keep the numbered section structure (`## 1. …` / `### 1.4 …`) when editing:
  each heading becomes one retrievable chunk, and its text is weighted into the ranking.

Point `APP_KNOWLEDGE_FILE` at a different markdown file to swap the corpus without a code
change.
