import { test, expect, type Page } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Пароль",{exact:true}).fill(process.env.DEMO_PASSWORD||"demo-password-123");
  await page.getByRole("button",{name:"Войти в систему"}).click();
  await expect(page.getByText("Mock provider · без внешнего API",{exact:true})).toBeVisible();
}

test("XLSX → RQ agent tools → manager review → real documents", async ({page})=>{
  await login(page);
  await page.getByLabel("Или загрузите XLSX").setInputFiles("tests/fixtures/request.xlsx");
  await page.getByRole("button",{name:"Зарегистрировать заявку"}).click();
  await page.getByRole("button",{name:"Разобрать заявку и создать черновик"}).click();
  await expect(page.getByRole("status")).toContainText("Черновик готов",{timeout:45000});
  await expect(page.getByLabel("Количество 1",{exact:true})).toHaveValue("2");
  await expect(page.getByLabel("Количество 2",{exact:true})).toHaveValue("1");
  await expect(page.getByRole("link",{name:"Скачать PDF"})).toHaveCount(0);
  await page.getByText("Инструменты и журнал агента",{exact:false}).click();
  await expect(page.locator(".agent-call").filter({hasText:"tool / search_catalog"})).toHaveCount(2);
  await page.getByRole("button",{name:"Подтвердить цены"}).click();
  await expect(page.getByRole("link",{name:"Скачать PDF"})).toBeVisible({timeout:100000});
  const pdf=await page.request.get((await page.getByRole("link",{name:"Скачать PDF"}).getAttribute("href"))!);
  const docx=await page.request.get((await page.getByRole("link",{name:"Скачать DOCX"}).getAttribute("href"))!);
  expect(pdf.status()).toBe(200);expect((await pdf.body()).subarray(0,4).toString()).toBe("%PDF");
  expect(docx.status()).toBe(200);
  await mkdir("../output",{recursive:true});
  await writeFile("../output/agent-proposal-example.pdf",await pdf.body());
  await writeFile("../output/agent-proposal-example.docx",await docx.body());
  await page.getByText("Инструменты и журнал агента",{exact:false}).click();
  await page.evaluate(()=>window.scrollTo(0,0));
  await page.screenshot({path:"../output/ui-agent-desktop.png",fullPage:true});
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:"../output/ui-agent-mobile.png",fullPage:true});
});

test("ambiguous request → clarification → one verified draft",async({page})=>{
  await login(page);
  await page.getByLabel("Обращение клиента").fill("Клапан Ду25, 2 шт.");
  await page.getByRole("button",{name:"Зарегистрировать заявку"}).click();
  await page.getByRole("button",{name:"Разобрать заявку и создать черновик"}).click();
  await expect(page.getByRole("status")).toContainText("Ручная проверка",{timeout:45000});
  await expect(page.locator(".review-questions")).toContainText("несколько исполнений");
  await expect(page.getByRole("button",{name:"Подтвердить цены"})).toHaveCount(0);
  await page.getByLabel("Уточнённый перечень").fill("SKU-0001, 2 шт.");
  await page.getByRole("button",{name:"Разобрать заявку и создать черновик"}).click();
  await expect(page.getByRole("status")).toContainText("Черновик готов",{timeout:45000});
  await expect(page.getByRole("button",{name:"Подтвердить цены"})).toBeEnabled();
});
