import { CitationList, CitedText } from "@/components/knowledge/citations";
import type { TeamOutput } from "@/lib/api/teams";

export function TeamOutputView({ output }: { output: TeamOutput }) {
  const citations = output.citations ?? [];
  return (
    <div className="team-output">
      <div className="result-hero"><div><p className="eyebrow">VALIDATED ANALYSIS</p><h3>{output.company}</h3></div><div className="result-score">{output.opportunity_score}<span>/ 100 opportunity score</span></div></div>
      <p>{output.summary}</p>
      <dl className="details">
        <dt>Strengths</dt>
        <dd>{output.strengths.join("; ") || "none"}</dd>
        <dt>Risks</dt>
        <dd>{output.risks.join("; ") || "none"}</dd>
        <dt>Next steps</dt>
        <dd>
          <ol className="plain-list">
            {output.recommended_next_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </dd>
        <dt>Validation</dt>
        <dd>
          {output.validation.valid ? "Approved" : "Rejected"} · confidence{" "}
          {Math.round(output.validation.confidence * 100)}%
          {output.revisions ? ` · ${output.revisions} revision` : ""}
        </dd>
        {citations.length > 0 && (
          <>
            <dt>Knowledge findings</dt>
            <dd>
              <ul className="plain-list cited-text">
                {output.key_findings
                  .filter((finding) => /\[K\d+\]/.test(finding))
                  .map((finding) => (
                    <li key={finding}>
                      <CitedText text={finding.replace(/^Knowledge: /, "")} citations={citations} />
                    </li>
                  ))}
              </ul>
            </dd>
          </>
        )}
        <dt>Sources</dt>
        <dd>
          {[...output.sources, ...new Set(citations.map((citation) => citation.source_name))].join(
            "; ",
          )}
        </dd>
      </dl>
      {citations.length > 0 && <CitationList citations={citations} />}
    </div>
  );
}
