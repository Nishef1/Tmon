import Link from "next/link";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { formatValue, type NumKind } from "@/lib/format";

type Props = {
  /** Glossary entry the number links to. Required: every number on the site explains itself. */
  term: GlossaryKey;
  value: number | null | undefined;
  kind?: NumKind;
  digits?: number;
  signed?: boolean;
};

export function Num({ term, value, kind = "plain", digits, signed }: Props) {
  const text = formatValue(value, kind, digits, signed);
  return (
    <Link
      href={`/glossary/${term}`}
      className="num"
      title={`${GLOSSARY[term].fa} — توضیح در واژه‌نامه`}
    >
      <bdi dir="ltr">{text}</bdi>
    </Link>
  );
}
