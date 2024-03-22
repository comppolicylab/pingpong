import DOMPurify from 'isomorphic-dompurify';

// Ensure that all links open in a new tab
DOMPurify.addHook('afterSanitizeAttributes', function (node) {
  if (node?.tagName === 'A') {
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer external');
  }
});

export default DOMPurify;
