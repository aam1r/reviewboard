/*
 * Provides review capabilities for Markdown files.
 */
RB.MarkdownReviewable = RB.AbstractReviewable.extend({
    defaults: _.defaults({
        caption: '',
        attachmentID: null
    }, RB.AbstractReviewable.prototype.defaults)
});
