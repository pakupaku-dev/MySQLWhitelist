-- MySQLWhitelist と同じデータベースを選択して実行してください。
-- 既存テーブルは変更しません。
CREATE TABLE IF NOT EXISTS `whitelist` (
    `id` INT(11) NOT NULL AUTO_INCREMENT,
    `steamid` VARCHAR(255) NOT NULL,
    PRIMARY KEY (`id`)
);

CREATE TABLE IF NOT EXISTS `player_info` (
    `steamid` VARCHAR(255) NOT NULL,
    `personaname` VARCHAR(255) NOT NULL,
    `avatar` TEXT NOT NULL,
    `discord_id` BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (`steamid`),
    UNIQUE KEY `player_info_discord_id` (`discord_id`)
) DEFAULT CHARACTER SET utf8mb4;

-- main.py は SELECT * の先頭2列を steamid / discord_id として扱います。
CREATE TABLE IF NOT EXISTS `blocked_users` (
    `steamid` VARCHAR(255) NOT NULL,
    `discord_id` BIGINT UNSIGNED NULL,
    PRIMARY KEY (`steamid`),
    UNIQUE KEY `blocked_users_discord_id` (`discord_id`)
);
