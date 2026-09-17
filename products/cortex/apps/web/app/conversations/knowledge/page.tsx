import { EvidenceLookup } from "@/components/evidence-lookup";
import { KnowledgeAnswer } from "@/components/knowledge-answer";

export default function KnowledgePage() {
  return <section className="knowledge-view"><header className="conversation-header"><p className="eyebrow">Read-only evidence</p><h1>Knowledge lookup</h1></header><KnowledgeAnswer /><EvidenceLookup /></section>;
}
