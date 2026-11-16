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

/** Hover text: the term and the first sentence of its definition. */
function hint(term: GlossaryKey): string {
  const g = GLOSSARY[term];
  const first = g.definition.split(/(?<=[.؛؟!])\s/)[0] ?? "";
  return `${g.fa}: ${first} (توضیح کامل در واژه‌نامه)`;
}

export function Num({ term, value, kind = "plain", digits, signed }: Props) {
  const text = formatValue(value, kind, digits, signed);
  return (
    <Link href={`/glossary/${term}`} className="num" title={hint(term)}>
      <bdi dir="ltr">{text}</bdi>
    </Link>
  );
}
