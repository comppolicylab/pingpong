import renderMathInElement from "katex/contrib/auto-render";

export const renderMath = (el: HTMLElement) => {
  console.log("Trying to render math", el.innerHTML);
  //renderMathInElement(el);
};
