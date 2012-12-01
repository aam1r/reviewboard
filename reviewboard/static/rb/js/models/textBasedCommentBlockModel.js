RB.TextCommentBlock = RB.FileAttachmentCommentBlock.extend({
    defaults: _.defaults({
        x: null,
        y: null,
        width: null,
        height: null
    }, RB.AbstractCommentBlock.prototype.defaults),

    serializedFields: ['x', 'y', 'width', 'height'],

    parse: function(fields) {
        fields.x = parseInt(fields.x, 10) || undefined;
        fields.y = parseInt(fields.y, 10) || undefined;
        fields.width = parseInt(fields.width, 10) || undefined;
        fields.height = parseInt(fields.height, 10) || undefined;

        return fields;
    }
});

