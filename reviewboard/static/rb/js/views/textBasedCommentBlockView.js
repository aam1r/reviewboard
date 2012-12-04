/*
 * Provides a visual comment indicator to display comments for text-based file
 * attachments.
 *
 * This will show a comment indicator flag (a "ghost comment flag") beside the
 * content indicating there are comments there. It will also show the
 * number of comments, along with a tooltip showing comment summaries.
 *
 * This is meant to be used with a TextCommentBlock model.
 */
RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

    /*
     * Renders the comment block.
     *
     * Along with the block's flag icon, a floating tooltip will also be
     * created that displays summaries of the comments.
     *
     * After rendering, the block's style and count will be updated whenever
     * the appropriate state is changed in the model.
     */
    renderContent: function() {
        this._$ghostCommentFlag = $("<span/>")
            .addClass("commentflag")
            .append($("<span/>").addClass("commentflag-shadow"));

        this._$innerFlag = $("<span/>")
            .addClass("commentflag-inner")
            .appendTo(this._$ghostCommentFlag);

        this._$count = $("<span/>")
            .appendTo(this._$innerFlag);

        this.$el.append(this._$ghostCommentFlag);

        this.model.on('change:count', this._updateCount, this);
        this._updateCount();
    },

    /*
     * Positions the comment dlg to the side of the flag.
     */
    positionCommentDlg: function(commentDlg) {
        commentDlg.positionToSide(this._$ghostCommentFlag, {
            side: 'r',
            fitOnScreen: true
        });
    },

    /*
     * Updates the displayed count of comments.
     */
    _updateCount: function() {
        this._$count.text(this.model.get('count'));
    }
});
