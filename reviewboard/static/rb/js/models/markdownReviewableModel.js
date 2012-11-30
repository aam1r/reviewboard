/*
 * Provides review capabilities for Markdown files.
 */
RB.MarkdownReviewable = RB.AbstractReviewable.extend({
    defaults: _.defaults({
        caption: '',
        rendered: '',
        attachmentID: null
    }, RB.AbstractReviewable.prototype.defaults)
});
