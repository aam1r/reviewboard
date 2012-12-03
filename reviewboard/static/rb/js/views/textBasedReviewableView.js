/*
 * Base support for displaying a review UI for text-based file attachments.
 */
RB.TextBasedReviewableView = RB.FileAttachmentReviewableView.extend({
    commentBlockView: RB.TextBasedCommentBlockView,

    events: {
        'mouseenter .rendered-comment': '_onMouseEnter',
        'mouseleave .rendered-comment': '_onMouseLeave',
        'click .rendered-comment': '_onClick'
    },

    initialize: function() {
        RB.FileAttachmentReviewableView.prototype.initialize.call(this);

        this.on('commentBlockViewAdded', function(commentBlockView) {
            this._addCommentBlock(commentBlockView);
        }, this);
    },

    renderContent: function() {
        this._$rendered = $(this.model.get('rendered'));

        this._applyCommentWrapper();
        this.$el.html(this._$rendered);

        return this;
    },

    _applyCommentWrapper: function() {
        var child_id = 0;

        this._$rendered.each(function() {
            $(this)
                .attr('class', 'rendered-comment')
                .attr('data-child-id', child_id++);
        });
    },

    _addCommentBlock: function(commentBlockView) {
        var child_id = commentBlockView.model.get('child_id');
        var child = this.$el.find("[data-child-id='" + child_id + "']");

        child.append(commentBlockView.$el);
    },

    _onMouseEnter: function(evt) {
        var wrapper = $(evt.target).closest('.rendered-comment');
        wrapper.css('background-color', '#F0F0F0');
    },

    _onMouseLeave: function(evt) {
        var wrapper = $(evt.target).closest('.rendered-comment');
        wrapper.css('background-color', 'white');
    },

    _onClick: function(evt) {
        var wrapper = $(evt.target).closest('.rendered-comment');

        if (wrapper.has('.commentflag').length == 0) {
            var child_id = wrapper.data('child-id');

            this.createAndEditCommentBlock({
                child_id: child_id
            });
        }
    }
});
