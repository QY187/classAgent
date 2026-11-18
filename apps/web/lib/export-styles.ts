/** 自包含的屏幕预览与A4打印样式，不依赖站点CSS或远程字体。 */
export const lessonPrintStyles = `
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #edf0f4; color: #243247; font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; font-size: 14px; line-height: 1.85; }
.report { max-width: 880px; margin: 36px auto; padding: 52px 60px 32px; background: #fff; box-shadow: 0 8px 40px #2432470d; }
.report-header { border-bottom: 2px solid #263f64; padding-bottom: 24px; margin-bottom: 30px; }
.eyebrow { display: flex; align-items: center; gap: 14px; color: #748197; font-size: 12px; letter-spacing: 1px; }
.brand { font-size: 17px; color: #263f64; font-weight: 750; letter-spacing: 0; }
h1 { font-size: 30px; line-height: 1.4; margin: 18px 0; letter-spacing: -.5px; overflow-wrap: anywhere; }
.metadata { display: flex; flex-wrap: wrap; gap: 6px 18px; color: #69788d; font-size: 12px; }
.section-heading { display: flex; gap: 12px; align-items: baseline; border-bottom: 1px solid #dce3ec; padding-bottom: 10px; margin: 28px 0 20px; break-after: avoid; }
.section-heading > span { color: #7388a5; font-size: 12px; font-weight: 700; }
h2 { font-size: 21px; line-height: 1.4; margin: 0; }
.section-heading small { color: #7c8999; font-size: 11px; margin-left: auto; font-weight: 400; }
h3 { font-size: 16px; margin: 25px 0 10px; color: #263f64; }
h4,h5,h6 { font-size: 14px; margin: 18px 0 8px; }
h1,h2,h3,h4,h5,h6 { break-after: avoid; }
p { margin: 8px 0 12px; white-space: pre-wrap; overflow-wrap: anywhere; orphans: 3; widows: 3; }
.summary-body > p:first-child:not(.empty) { background: #f1f5fa; border-left: 3px solid #6c86aa; padding: 14px 18px; margin-bottom: 24px; }
ul,ol { padding-left: 24px; margin: 10px 0 18px; }
li { padding-left: 3px; margin: 7px 0; overflow-wrap: anywhere; }
li p { margin: 5px 0; }
li ul,li ol { margin: 6px 0; }
blockquote { margin: 16px 0; padding: 4px 18px; border-left: 3px solid #9aaec8; color: #53657c; }
code { font-family: Consolas, monospace; background: #f1f3f6; padding: 2px 4px; overflow-wrap: anywhere; }
a { color: #263f64; overflow-wrap: anywhere; }
hr { border: 0; border-top: 1px solid #dce3ec; margin: 20px 0; }
ul[data-type="taskList"] { list-style: none; padding-left: 0; }
li[data-type="taskItem"] { display: flex; gap: 8px; align-items: baseline; }
li[data-type="taskItem"] > div { flex: 1; min-width: 0; }
.transcript-item { margin: 0 0 17px; padding-bottom: 14px; border-bottom: 1px solid #e9edf2; break-inside: avoid; }
.transcript-item.long-segment { break-inside: auto; }
.segment-meta { display: flex; flex-wrap: wrap; align-items: baseline; gap: 7px 14px; color: #748197; font-size: 11px; font-variant-numeric: tabular-nums; break-after: avoid; }
.segment-index { color: #a0acbb; min-width: 25px; }
.segment-meta strong { color: #354a67; font-size: 12px; overflow-wrap: anywhere; }
.transcript-item p { margin: 7px 0 0; }
.empty { color: #7c8999; padding: 12px 0; }
.report-footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #dce3ec; color: #8a96a6; font-size: 10px; }
@page { size: A4; margin: 18mm 17mm 20mm;
  @bottom-left { content: "ClassAgent · 课堂资料"; font-size: 8pt; color: #8491a2; font-family: "Microsoft YaHei", sans-serif; }
  @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; color: #8491a2; font-family: "Segoe UI", sans-serif; }
}
@media print {
  body { background: white; font-size: 10.25pt; line-height: 1.7; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .report { margin: 0; padding: 0; max-width: none; box-shadow: none; }
  h1 { font-size: 23pt; } h2 { font-size: 16pt; } h3 { font-size: 12pt; }
  .report-header { padding-bottom: 18px; margin-bottom: 22px; }
  .section-heading { margin: 20px 0 16px; }
  h3 { margin: 14px 0 6px; }
  p { margin: 6px 0 9px; }
  ul,ol { margin: 7px 0 10px; }
  li { margin: 4px 0; }
  .summary-body > ul > li,.summary-body > ol > li { break-inside: avoid; }
  .summary-body > p:first-child:not(.empty) { padding: 11px 15px; margin-bottom: 18px; }
  .new-page { break-before: page; }
  .new-page .section-heading { margin-top: 0; }
  .report-footer { display: none; }
}
@media screen and (max-width: 600px) {
  .report { padding: 26px 20px; margin: 0; } h1 { font-size: 25px; }
  .section-heading { flex-wrap: wrap; } .section-heading small { margin-left: 0; }
}
`;
