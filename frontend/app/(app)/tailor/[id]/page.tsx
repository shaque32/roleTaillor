import type { Metadata } from "next";
import { Review } from "./Review";

export const metadata: Metadata = { title: "Review" };

export default function ReviewPage() {
  return <Review />;
}
