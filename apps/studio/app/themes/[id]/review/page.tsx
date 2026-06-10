"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { BuildReview } from "../../../../components/BuildReview";
import { StepFooter } from "../../../../components/WorkflowSteps";

export default function ReviewPage() {
  const { id: themeId } = useParams<{ id: string }>();
  return (
    <section>
      <h2 style={{ marginBottom: 4 }}>Review the build</h2>
      <p style={{ color: "#475569", marginTop: 0 }}>
        <small>
          One map of everything this theme has before you publish: the data
          pipeline (where it’s full or empty), each company’s coverage, and the
          supplier→customer relationships the build produced. Use it to see{" "}
          <strong>why trade edges are 0</strong> and what to fill. Edges come
          only from extracted claims — financials, calendar and tickets quantify
          and date a trade, they never create one. Then head to{" "}
          <Link href={`/themes/${themeId}/publish`}>Publish</Link>.
        </small>
      </p>

      <BuildReview themeId={themeId} />

      <StepFooter themeId={themeId} currentKey="review" />
    </section>
  );
}
