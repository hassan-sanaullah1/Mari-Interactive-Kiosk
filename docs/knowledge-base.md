# Knowledge base

The grounding corpus for the kiosk lives in `server/data/` and is ingested by the retrieval
layer in `server/rag/` (see [retrieval.md](retrieval.md)).

- `server/data/mari_energies_knowledge_base.md` is the Mari Energies Limited knowledge
  base, converted from the source `MariEnergies_RAG_Knowledge_Base_V2.docx`. Retrieval
  keys off `##`/`###` headings, so keep the numbered section structure (`## 1. …` /
  `### 1.4 …`) when editing: each heading becomes one retrievable chunk, and its text is
  weighted into the ranking.

Point `APP_KNOWLEDGE_FILE` at a different markdown file to swap the corpus without a code
change.
