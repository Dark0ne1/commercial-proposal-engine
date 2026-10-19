import {test,expect} from "@playwright/test";
import {formatMoney} from "../app/money";
test("money display preserves kopecks above the Number precision limit",()=>{
  expect(formatMoney("10000000000000000.01").replace(/\s/g," ")).toBe("10 000 000 000 000 000,01 ₽");
  expect(formatMoney("0.00")).toBe("0,00 ₽");
  expect(formatMoney("100.10")).toBe("100,10 ₽");
});
