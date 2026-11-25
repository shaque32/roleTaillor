import type { Metadata } from "next";
import { Suspense } from "react";
import { ResumeDetailView } from "./ResumeDetailView";

export const metadata: Metadata = { title: "Resume" };

export default function ResumePage() {
  return (
    <Suspense>
      <ResumeDetailView />
    </Suspense>
  );
}
