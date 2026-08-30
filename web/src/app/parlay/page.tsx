import { PageHeader } from "@/components/PageHeader";
import { ParlayBuilder, type PickRow } from "@/components/ParlayBuilder";
import { getParlayLegs } from "@/lib/queries";

export const dynamic = "force-dynamic";

export default async function ParlayPage() {
  const legs = await getParlayLegs();
  return (
    <div>
      <PageHeader
        index="04"
        title="Parlay Generator"
        sub="Build a 2–5 leg ticket and see what the model thinks it is actually worth. Legs are correlated — a quarterback and his WR1 rise and fall together — so the rating is a Gaussian copula over the legs, not a product of their probabilities."
      />
      <ParlayBuilder available={legs as unknown as PickRow[]} />
    </div>
  );
}
