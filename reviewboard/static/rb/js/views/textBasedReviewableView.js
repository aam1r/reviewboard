/*
 * Base for text-based review UIs.
 *
 * This will display all existing comments on an element by displaying a comment
 * indicator beside it. Users can place a comment by clicking on a line, which
 * will get a light-grey background color upon mouseover, and placing a comment
 * in the comment dialog that is displayed.
 */
RB.TextBasedReviewableView = RB.FileAttachmentReviewableView.extend({
    commentBlockView: RB.TextBasedCommentBlockView,

    events: {
        'click .text-review-ui-container': '_onClick'
    },

    /*
     * Initializes the view.
     */
    initialize: function() {
        RB.FileAttachmentReviewableView.prototype.initialize.call(this);
        this.on('commentBlockViewAdded', this._addCommentBlock, this);
    },

    /*
     * Renders the view.
     *
     * This will wrap each parent in the rendered HTML with a 'div' tag. The
     * wrapper will be used to apply styling and handle events related to
     * showing and creating comments.
     */
    renderContent: function() {
        this._$rendered = $(this.model.get('rendered'));
        this._$wrappedComments = '';

        this._applyCommentWrapper();
        this.$el.html(this._$wrappedComments);

        return this;
    },

    /*
     * Wrap each parent element in a 'div'. A class is also used for the wrapper
     * to identify it as a comment wrapper. Each wrapper also has a unique,
     * auto-incremented id to distinguish the child element from other elements.
     */
    _applyCommentWrapper: function() {
        var self = this,
            child_id = 0;

        this._$rendered.each(function() {
            var wrapper = $('<div />')
                .attr('class', 'text-review-ui-container')
                .attr('data-child-id', child_id++)
                .append($(this));

            self._$wrappedComments += wrapper[0].outerHTML;
        });
    },

    /*
     * Adds the comment view to the element the comment was created on.
     */
    _addCommentBlock: function(commentBlockView) {
        var child_id = commentBlockView.model.get('child_id'),
            child = this.$el.find("[data-child-id='" + child_id + "']");

        child.prepend(commentBlockView.$el);
    },

    /*
     * When an element is clicked, display the comment dialog if the element
     * has no comments so far.
     */
    _onClick: function(evt) {
        var wrapper = $(evt.target).closest('.text-review-ui-container');

        if (wrapper.has('.commentflag').length == 0) {
            var child_id = wrapper.data('child-id');

            this.createAndEditCommentBlock({
                child_id: child_id
            });
        }
    }
});
