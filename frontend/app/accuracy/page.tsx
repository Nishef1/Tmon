import { redirect } from "next/navigation";

/** Merged into another page; old links keep working. */
export default function Moved() {
  redirect("/model#accuracy");
}
