// Fresh rule-test target for saga.money-as-floating-point. Never executed.

function bookFloats(): void {
  // ruleid: saga.money-as-floating-point
  const amount = 19.99;
  // ruleid: saga.money-as-floating-point
  let total: number = 0.0;
  // ruleid: saga.money-as-floating-point
  const price = parseFloat(rawPrice);
  // ruleid: saga.money-as-floating-point
  const balance = Number(rawBalance);
  // ruleid: saga.money-as-floating-point
  const ledger = { amount: 19.99, total: 44.99 };
  // ok: saga.money-as-floating-point
  const totalCents = 1999;
  // ok: saga.money-as-floating-point
  const computed = computeTotal();
  // ok: saga.money-as-floating-point
  const rate = 0.05;
  // ok: saga.money-as-floating-point
  const amount = new Decimal("19.99");
  // ok: saga.money-as-floating-point
  const ledgerInt = { amountCents: 1999 };
}
