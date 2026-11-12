import type { Ranking } from "@/lib/api";
import { jalali } from "@/lib/format";
import { Num } from "@/components/Num";

export function ExposureCard({ d }: { d: Ranking }) {
  return (
    <>
      {d.exposure && (
        <section className="card text-sm">
          <h2 className="font-bold">چند درصد سرمایه در سهام باشد؟</h2>
          <p className="mt-1">
            سطح مواجههٔ مدل در {jalali(d.exposure_date)}:{" "}
            <Num value={d.exposure.exposure} kind="percent" term="exposure_level" digits={1} />؛
            روند <Num value={d.exposure.trend} term="exposure_level" digits={2} />، مومنتوم{" "}
            <Num value={d.exposure.abs_mom} term="exposure_level" digits={2} />، سقف نوسان{" "}
            <Num value={d.exposure.vol_cap} term="exposure_level" digits={2} />، فشار صف فروش{" "}
            <Num value={d.exposure.stress} term="exposure_level" digits={3} />. باقی در اوراق با
            درآمد ثابت فرض می‌شود.
          </p>
        </section>
      )}
    </>
  );
}
