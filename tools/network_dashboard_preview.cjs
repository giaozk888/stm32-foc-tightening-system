// Headless development-only visual QA. Never connects to hardware.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
(async () => {
  const [url, token, out] = process.argv.slice(2);
  fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({headless:true,channel:process.env.PREVIEW_BROWSER_CHANNEL || 'msedge'});
  try {
    const page = await browser.newPage({viewport:{width:1360,height:900},acceptDownloads:true});
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);await page.locator('#token').fill(token);await page.locator('#connect').click();
    await page.waitForFunction(()=>document.querySelectorAll('#rows tr').length===2);
    if(await page.locator('#results').textContent()!=='1')throw new Error('result count wrong');
    if(!(await page.locator('#rows tr').first().textContent()).includes('不可用'))throw new Error('invalid observation rendered as a valid measurement');
    await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
    const downloadEvent=page.waitForEvent('download');await page.locator('#export').click();
    const download=await downloadEvent;await download.saveAs(path.join(out,'preview.csv'));
    const csv=fs.readFileSync(path.join(out,'preview.csv'),'utf8');
    if(!csv.includes('vbus_quality')||!csv.includes('AABBCCDDEEFF'))throw new Error('CSV fields missing');
    await page.locator('#kind').selectOption('1');
    await page.waitForFunction(()=>document.querySelectorAll('#rows tr').length===1);
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
    if(overflow)throw new Error('page horizontally overflows mobile viewport');
    if(errors.length)throw new Error(errors.join('; '));
    console.log('Dashboard desktop/mobile, result filter and CSV download PASS');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
