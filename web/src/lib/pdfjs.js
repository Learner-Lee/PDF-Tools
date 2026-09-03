/** 浏览器侧的 pdf.js 装配：只此一处配置 worker。 */
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export default pdfjs;
