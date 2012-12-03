RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

    initialize: function() {
        console.log('initialize in textbasecommentblockview');
    },

    renderContent: function() {
        console.log('render content in textbasedcommentblockview');

        this._$flag = $('<div/>')
            .addClass('selection-flag')
            .appendTo(this.$el);
    },

    positionCommentDlg: function(commentDlg) {
        commentDlg.positionToSide(this._$flag, {
            side: 'b',
            fitOnScreen: true
        });
    },
});
