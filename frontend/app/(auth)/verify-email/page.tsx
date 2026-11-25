import type { Metadata } from "next";
import { VerifyEmailStatus } from "@/components/VerifyEmailStatus";

export const metadata: Metadata = { title: "Confirm your email" };

export default function Page() {
  return <VerifyEmailStatus />;
}
