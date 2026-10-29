const { mathjax } = require("mathjax-full/js/mathjax.js");
const { TeX } = require("mathjax-full/js/input/tex.js");
const { SVG } = require("mathjax-full/js/output/svg.js");
const { liteAdaptor } = require("mathjax-full/js/adaptors/liteAdaptor.js");
const { RegisterHTMLHandler } = require("mathjax-full/js/handlers/html.js");
require("mathjax-full/js/input/tex/ams/AmsConfiguration.js");
require("mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js");
const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const tex = new TeX({
  packages: ["base", "ams", "newcommand"],
  maxBuffer: 12000,
  maxMacros: 1000,
});
const document = mathjax.document("", {
  InputJax: tex,
  OutputJax: new SVG({ fontCache: "none" }),
});
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  try {
    const node = document.convert(JSON.parse(input).tex, { display: true });
    const svg = adaptor.outerHTML(adaptor.firstChild(node));
    if (svg.includes('data-mml-node="merror"'))
      throw new Error("LaTeX 문법 또는 지원하지 않는 명령을 확인하세요.");
    process.stdout.write(svg);
  } catch (e) {
    process.stderr.write(e.message);
    process.exitCode = 1;
  }
});
